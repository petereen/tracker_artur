"""OYUNS ERP operator CLI (run inside the backend container).

    python -m scripts.platform_admin generate-license-keys [--kid oyuns-license-2]
    python -m scripts.platform_admin create-operator --email ops@oyuns.mn --role superadmin
    python -m scripts.platform_admin reset-2fa --email ops@oyuns.mn
    python -m scripts.platform_admin tenants
    python -m scripts.platform_admin rls-status

``create-operator`` reads the password from PLATFORM_OPERATOR_PASSWORD or
prompts for it; it never takes a password on the command line.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session


def _engine():
    from app.core.config import settings

    return create_engine(settings.SYNC_DATABASE_URL)


def generate_license_keys(args) -> int:
    from cryptography.hazmat.primitives import serialization

    from app.services.licensing import generate_keypair, load_public_key

    private_pem, public_pem = generate_keypair()
    raw_public = load_public_key(public_pem).public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print("# Keep the private key only on the service that issues licenses (secret store):")
    print(f"LICENSE_SIGNING_KEY_ID={args.kid}")
    print("LICENSE_SIGNING_PRIVATE_KEY=" + private_pem.strip().replace("\n", "\\n"))
    print("\n# Verifiers (and key rotation) need only the public key:")
    print("LICENSE_PUBLIC_KEYS=" + json.dumps({args.kid: base64.b64encode(raw_public).decode()}))
    return 0


def create_operator(args) -> int:
    from app.core.security import hash_account_password
    from app.models.platform import PlatformOperator

    password = os.environ.get("PLATFORM_OPERATOR_PASSWORD") or getpass.getpass("Operator password (min 12 chars): ")
    if len(password) < 12:
        print("Password must have at least 12 characters", file=sys.stderr)
        return 2
    email = args.email.strip().lower()
    with Session(_engine()) as session:
        session.execute(text("SELECT set_config('app.system_context', 'on', true)"))
        if session.scalar(select(PlatformOperator.id).where(func.lower(PlatformOperator.email) == email)):
            print(f"Operator {email} already exists", file=sys.stderr)
            return 1
        session.add(PlatformOperator(email=email, display_name=args.name, role=args.role, password_hash=hash_account_password(password)))
        session.commit()
    print(f"Created {args.role} operator {email}")
    return 0


def reset_2fa(args) -> int:
    from app.models.platform import PlatformOperator

    email = args.email.strip().lower()
    with Session(_engine()) as session:
        session.execute(text("SELECT set_config('app.system_context', 'on', true)"))
        operator = session.scalar(select(PlatformOperator).where(func.lower(PlatformOperator.email) == email))
        if operator is None:
            print(f"Operator {email} not found", file=sys.stderr)
            return 1
        operator.totp_secret_enc = None
        operator.totp_enabled_at = None
        operator.totp_last_step = None
        operator.totp_recovery_codes = []
        operator.failed_login_count = 0
        operator.locked_until = None
        session.commit()
    print(f"Two-factor authentication reset for {email}; it is set up again on the next login")
    return 0


def tenants(_args) -> int:
    with Session(_engine()) as session:
        session.execute(text("SELECT set_config('app.system_context', 'on', true)"))
        rows = session.execute(text(
            """
            SELECT o.id, o.slug, o.name, o.status, o.is_primary, o.seat_limit, o.license_expires_at,
                   (SELECT count(*) FROM user_accounts a WHERE a.organization_id = o.id
                      AND a.status IN ('active','invited','locked') AND coalesce(a.preferences->>'system_agent','') = '') AS seats_used
            FROM organizations o ORDER BY o.is_primary DESC, o.id
            """
        )).all()
    for row in rows:
        limit = "∞" if row.seat_limit is None else row.seat_limit
        primary = " (primary)" if row.is_primary else ""
        print(f"{row.id:>4}  {row.slug:<24} {row.status:<18} seats {row.seats_used}/{limit:<6} license until {row.license_expires_at or '—'}  {row.name}{primary}")
    return 0


def rls_status(_args) -> int:
    with Session(_engine()) as session:
        role = session.execute(text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
        protected = session.scalar(text(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'r' AND n.nspname = current_schema() AND c.relrowsecurity AND c.relforcerowsecurity"
        ))
    print(f"connected as {role[0]} superuser={role[1]} bypassrls={role[2]}; tables with forced RLS: {protected}")
    if role[1] or role[2]:
        print("RLS is NOT enforced for this role — run the API as the oyuns_app role (ops/sql/oyuns_app_role.sql).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="platform_admin", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    keys = commands.add_parser("generate-license-keys")
    keys.add_argument("--kid", default="oyuns-license-1")
    keys.set_defaults(handler=generate_license_keys)
    operator = commands.add_parser("create-operator")
    operator.add_argument("--email", required=True)
    operator.add_argument("--name")
    operator.add_argument("--role", choices=("superadmin", "support"), default="superadmin")
    operator.set_defaults(handler=create_operator)
    reset = commands.add_parser("reset-2fa")
    reset.add_argument("--email", required=True)
    reset.set_defaults(handler=reset_2fa)
    commands.add_parser("tenants").set_defaults(handler=tenants)
    commands.add_parser("rls-status").set_defaults(handler=rls_status)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
