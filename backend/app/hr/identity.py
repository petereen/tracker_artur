"""Worker identity and employment vocabulary shared by HR schemas and services.

Kept free of database/FastAPI imports so validation can be unit-tested alone.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any


# Employment statuses. Only the "working" ones keep the person active
# (surveys, payroll, app access); the rest switch is_active off.
WORKING_STATUSES = ("active", "probation")
EMPLOYMENT_STATUSES = (*WORKING_STATUSES, "on_leave", "suspended", "inactive", "terminated")
EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "intern")
GENDERS = ("male", "female")

_REGISTRATION_RE = re.compile(r"^[А-ЯЁӨҮ]{2}\d{8}$")


def normalize_registration_number(value: str | None) -> str | None:
    """Uppercase and strip spaces: 'уб 99011512' -> 'УБ99011512'. Empty -> None."""
    if value is None:
        return None
    cleaned = re.sub(r"[\s-]", "", value).upper()
    return cleaned or None


def parse_registration_number(value: str) -> dict[str, Any]:
    """Validate a Mongolian registration number and decode what it carries.

    Digits 1-6 are the birth date as YYMMDD; people born in 2000 or later have
    20 added to the month. The second-to-last digit is odd for men, even for
    women. Raises ValueError when the format or embedded date is invalid.
    """
    if not _REGISTRATION_RE.match(value):
        raise ValueError("Регистрын дугаар 2 кирилл үсэг + 8 оронтой тоо байх ёстой (жишээ: УБ99011512)")
    digits = value[2:]
    year, month, day = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
    if month > 20:
        month -= 20
        year += 2000
    else:
        year += 1900
    try:
        birthday = date(year, month, day)
    except ValueError as exc:
        raise ValueError("Регистрын дугаар дахь төрсөн огноо буруу байна") from exc
    if birthday > date.today():
        raise ValueError("Регистрын дугаар дахь төрсөн огноо буруу байна")
    return {"birthday": birthday, "gender": "male" if int(digits[6]) % 2 else "female"}
