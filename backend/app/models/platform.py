"""Platform (operator) level models for the OYUNS ERP SaaS.

These tables sit above the tenants: subscription plans, signed license keys,
tenant domains, the operator accounts of the superadmin console and their
audit trail. Operators are deliberately *not* ``user_accounts``: no tenant
role, session or token can reach the console. See docs/multi-tenancy.md.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


TENANT_STATUSES = ("pending_activation", "active", "suspended", "terminated")
BILLING_CYCLES = ("monthly", "quarterly", "yearly", "custom")
LICENSE_STATUSES = ("issued", "active", "superseded", "revoked")
OPERATOR_ROLES = ("superadmin", "support")


class SubscriptionPlan(Base):
    """A package (Starter / Professional / Enterprise …) used as license defaults."""

    __tablename__ = "subscription_plans"
    __table_args__ = (
        CheckConstraint("billing_cycle IN ('monthly','quarterly','yearly','custom')", name="ck_subscription_plans_billing_cycle"),
        CheckConstraint("seat_limit IS NULL OR seat_limit > 0", name="ck_subscription_plans_seat_limit"),
    )

    id = Column(Integer, primary_key=True)
    code = Column(Text, nullable=False, unique=True)
    name = Column(Text, nullable=False)
    description = Column(Text)
    seat_limit = Column(Integer)
    features = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    billing_cycle = Column(Text, nullable=False, server_default="monthly", default="monthly")
    price_amount = Column(Numeric(14, 2))
    currency = Column(String(3), nullable=False, server_default="MNT", default="MNT")
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    sort_order = Column(Integer, nullable=False, server_default="0", default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class TenantLicense(Base):
    """Registry of every issued license token.

    The token itself is an Ed25519-signed JWS (``app.services.licensing``);
    this row is the revocation/state list the verifier consults. ``public_id``
    is the token's ``jti``. At most one license per tenant is ``active``.
    """

    __tablename__ = "tenant_licenses"
    __table_args__ = (
        CheckConstraint("status IN ('issued','active','superseded','revoked')", name="ck_tenant_licenses_status"),
        CheckConstraint("seat_limit >= 1", name="ck_tenant_licenses_seat_limit"),
        CheckConstraint("expires_at > valid_from", name="ck_tenant_licenses_window"),
        Index("ix_tenant_licenses_org_status", "organization_id", "status"),
        Index("uq_tenant_licenses_active", "organization_id", unique=True, postgresql_where=sa_text("status = 'active'")),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    plan_code = Column(Text)
    seat_limit = Column(Integer, nullable=False)
    features = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    billing_cycle = Column(Text, nullable=False, server_default="monthly", default="monthly")
    valid_from = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(Text, nullable=False, server_default="issued", default="issued")
    key_id = Column(Text, nullable=False)
    token = Column(Text, nullable=False)
    token_sha256 = Column(String(64), nullable=False, unique=True)
    supersedes_id = Column(Integer, ForeignKey("tenant_licenses.id", ondelete="SET NULL"))
    notes = Column(Text)
    issued_by_operator_id = Column(Integer, ForeignKey("platform_operators.id", ondelete="SET NULL"))
    issued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    activated_at = Column(DateTime(timezone=True))
    activated_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    activated_by_operator_id = Column(Integer, ForeignKey("platform_operators.id", ondelete="SET NULL"))
    revoked_at = Column(DateTime(timezone=True))
    revoked_reason = Column(Text)
    revoked_by_operator_id = Column(Integer, ForeignKey("platform_operators.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class TenantDomain(Base):
    """Custom domains mapped to a tenant (subdomains derive from the slug)."""

    __tablename__ = "tenant_domains"
    __table_args__ = (
        CheckConstraint("hostname = lower(hostname)", name="ck_tenant_domains_lowercase"),
        Index("ix_tenant_domains_org", "organization_id"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    hostname = Column(Text, nullable=False, unique=True)
    verification_token = Column(Text, nullable=False)
    # ``verified_at`` is what routes traffic: the middleware resolves only
    # verified hostnames. Cloudflare domains get it once the custom hostname
    # and its certificate are both active.
    verified_at = Column(DateTime(timezone=True))
    # ``manual`` (operator-attested) or ``cloudflare`` (Cloudflare for SaaS).
    provider = Column(Text, nullable=False, server_default="manual", default="manual")
    provider_hostname_id = Column(Text, unique=True)
    status = Column(Text, nullable=False, server_default="pending", default="pending")
    ssl_status = Column(Text)
    # Last DNS records the customer has to create (CNAME + TXT validation).
    dns_records = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    last_error = Column(Text)
    last_checked_at = Column(DateTime(timezone=True))
    created_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


TELEGRAM_BOT_STATUSES = ("pending", "active", "error", "disabled")


class TenantTelegramBot(Base):
    """A tenant's own Telegram bot (BotFather token), one per tenant.

    ``pending`` bots are already polled so the handshake ``/start`` from the
    tenant admin can arrive; the handshake turns them ``active``. Tokens are
    encrypted with ``secret_box`` and never leave the API.
    """

    __tablename__ = "tenant_telegram_bots"
    __table_args__ = (
        CheckConstraint("status IN ('pending','active','error','disabled')", name="ck_tenant_telegram_bots_status"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True)
    bot_id = Column(BigInteger, nullable=False, unique=True)
    bot_username = Column(Text)
    bot_name = Column(Text)
    token_enc = Column(Text, nullable=False)
    token_sha256 = Column(String(64), nullable=False, unique=True)
    status = Column(Text, nullable=False, server_default="pending", default="pending")
    handshake_code_enc = Column(Text)
    handshake_expires_at = Column(DateTime(timezone=True))
    handshake_completed_at = Column(DateTime(timezone=True))
    handshake_telegram_id = Column(Text)
    # Heartbeat written by the bot runner while it polls this bot.
    last_seen_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    connected_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class PlatformOperator(Base):
    """A system operator of the superadmin console (never a tenant user)."""

    __tablename__ = "platform_operators"
    __table_args__ = (
        CheckConstraint("role IN ('superadmin','support')", name="ck_platform_operators_role"),
        CheckConstraint("status IN ('active','disabled')", name="ck_platform_operators_status"),
    )

    id = Column(Integer, primary_key=True)
    email = Column(Text, nullable=False, unique=True)
    display_name = Column(Text)
    password_hash = Column(Text, nullable=False)
    role = Column(Text, nullable=False, server_default="superadmin", default="superadmin")
    status = Column(Text, nullable=False, server_default="active", default="active")
    failed_login_count = Column(Integer, nullable=False, server_default="0", default=0)
    locked_until = Column(DateTime(timezone=True))
    last_login_at = Column(DateTime(timezone=True))
    # Two-factor login (TOTP). The secret is encrypted with ``secret_box``; it
    # is only a pending enrolment until ``totp_enabled_at`` is set.
    totp_secret_enc = Column(Text)
    totp_enabled_at = Column(DateTime(timezone=True))
    # Last accepted time step: a code cannot be used twice.
    totp_last_step = Column(BigInteger)
    # SHA-256 of the unused one-time recovery codes.
    totp_recovery_codes = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class PlatformAuditLog(Base):
    """Append-only trail of operator actions; survives tenant deletion."""

    __tablename__ = "platform_audit_logs"
    __table_args__ = (Index("ix_platform_audit_logs_org_created", "organization_id", "created_at"),)

    id = Column(Integer, primary_key=True)
    operator_id = Column(Integer, ForeignKey("platform_operators.id", ondelete="SET NULL"))
    # A tenant admin action (license activation) records the account instead.
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"))
    action = Column(Text, nullable=False)
    target_type = Column(Text)
    target_id = Column(Text)
    details = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    ip_address = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
