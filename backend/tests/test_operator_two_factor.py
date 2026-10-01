"""Operator console two-factor login: TOTP codes, recovery codes, tokens."""

import base64

from app.core.security import (
    create_platform_access_token,
    create_platform_mfa_token,
    decode_platform_access_token,
    decode_platform_mfa_token,
    decode_token,
)
from app.routers.platform import OperatorPatch, operator_view, reset_two_factor
from app.models.platform import PlatformOperator
from app.services import totp

# RFC 6238 appendix B (SHA-1), truncated to six digits.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


def test_codes_match_the_rfc_6238_vectors():
    assert totp.code_at(RFC_SECRET, 59 // 30) == "287082"
    assert totp.code_at(RFC_SECRET, 1111111109 // 30) == "081804"
    assert totp.code_at(RFC_SECRET, 1234567890 // 30) == "005924"
    assert totp.code_at(RFC_SECRET, 20000000000 // 30) == "353130"


def test_verify_allows_clock_drift_and_refuses_replay():
    now = 1234567890
    step = now // 30
    assert totp.verify(RFC_SECRET, "005924", now=now) == step
    assert totp.verify(RFC_SECRET, " 005 924 ", now=now) == step
    # One step of drift either way, not two.
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, step - 1), now=now) == step - 1
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, step + 1), now=now) == step + 1
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, step + 2), now=now) is None
    assert totp.verify(RFC_SECRET, "abcdef", now=now) is None
    assert totp.verify(RFC_SECRET, "0059240", now=now) is None
    # A code at or before the last accepted step is spent.
    assert totp.verify(RFC_SECRET, "005924", last_step=step, now=now) is None
    assert totp.verify(RFC_SECRET, "005924", last_step=step - 1, now=now) == step


def test_secret_and_provisioning_uri_work_with_authenticator_apps():
    secret = totp.generate_secret()
    assert len(secret) == 32 and secret.isalnum() and "=" not in secret
    assert totp.verify(secret, totp.code_at(secret, totp.current_step())) is not None
    uri = totp.provisioning_uri(secret, "ops@oyuns.mn", "OYUNS ERP Console")
    assert uri.startswith("otpauth://totp/OYUNS%20ERP%20Console%3Aops%40oyuns.mn?")
    assert f"secret={secret}" in uri and "issuer=OYUNS+ERP+Console" in uri and "digits=6" in uri and "period=30" in uri


def test_recovery_codes_are_single_use_and_stored_hashed():
    codes = totp.generate_recovery_codes()
    assert len(set(codes)) == 10 and all(len(code) == 11 and code[5] == "-" for code in codes)
    hashes = [totp.hash_recovery_code(code) for code in codes]
    assert not set(codes) & set(hashes)
    remaining = totp.consume_recovery_code(hashes, codes[3].upper().replace("-", " "))
    assert remaining is not None and len(remaining) == 9
    assert totp.consume_recovery_code(remaining, codes[3]) is None
    assert totp.consume_recovery_code(hashes, "aaaaa-aaaaa") is None


def test_the_password_step_token_is_not_a_session():
    pending = create_platform_mfa_token(7)
    assert decode_platform_mfa_token(pending)["sub"] == "7"
    assert decode_platform_access_token(pending) is None
    assert decode_token(pending) is None
    assert decode_platform_mfa_token(create_platform_access_token(7, "superadmin")) is None


def test_reset_clears_the_enrolment():
    operator = PlatformOperator(id=1, email="ops@oyuns.mn", role="superadmin", status="active", totp_secret_enc="x",
                                totp_enabled_at="2026-10-01T00:00:00Z", totp_last_step=5, totp_recovery_codes=["h"], failed_login_count=3)
    assert operator_view(operator)["two_factor_enabled"] is True
    reset_two_factor(operator)
    assert operator_view(operator)["two_factor_enabled"] is False
    assert operator.totp_secret_enc is None and operator.totp_recovery_codes == [] and operator.failed_login_count == 0
    assert "totp_secret_enc" not in operator_view(operator)
    assert OperatorPatch().reset_two_factor is False
