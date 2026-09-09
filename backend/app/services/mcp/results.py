"""Bounded, redacted result envelopes returned by every MCP tool."""
from __future__ import annotations

import json
import re
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

log = logging.getLogger(__name__)

MAX_RESULT_BYTES = 32 * 1024
FORBIDDEN_KEYS = frozenset({
    "token", "token_hash", "storage_key", "telegram_id", "encrypted_payload",
    "password", "password_hash", "access_token", "refresh_token", "raw_id",
})

@dataclass(frozen=True, slots=True)
class SanitizationPolicy:
    trusted_operational_paths: frozenset[tuple[str, ...]] = frozenset()
    max_depth: int = 12


HARD_SECRET_PATTERNS = {
    "openai_key": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    "bearer": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    "postgres_uri": re.compile(r"(?i)\bpostgres(?:ql)?(?:\+[a-z0-9_]+)?://[^\s]+"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    "bcrypt": re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}"),
    "argon2": re.compile(r"\$argon2(?:id|i|d)\$[^\s]+"),
    "pbkdf2": re.compile(r"(?i)\bpbkdf2_(?:sha256|sha512)\$[^\s]+"),
}
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
_OPERATIONAL_SECRET_PATTERN = re.compile(r"(?i)\b(?:password|passcode|pin|door\s+code|access\s+code)\s*[:=]\s*[^\s,;]+")


def sanitize_text(value: str, *, allow_operational_content: bool) -> str:
    output = value
    for name, pattern in HARD_SECRET_PATTERNS.items():
        count = len(pattern.findall(output))
        if count:
            log.debug("mcp_result_redaction pattern=%s count=%d", name, count)
            output = pattern.sub("[REDACTED:SYSTEM_SECRET]", output)
    if not allow_operational_content:
        output = _OPERATIONAL_SECRET_PATTERN.sub("[REDACTED:OPERATIONAL_SECRET]", output)
    return output


def _forbidden_key(key: object) -> bool:
    normalized = str(key).casefold()
    return (
        normalized in FORBIDDEN_KEYS
        or normalized == "id"
        or normalized.endswith("_id")
        or normalized.endswith("_ids")
)
DEFAULT_STATUS_CODE = {
    "denied": "ACCESS_DENIED",
    "empty": "NOT_FOUND_OR_NOT_VISIBLE",
    "indexing": "CONTENT_INDEXING_PENDING",
    "partial": "CONTENT_ENRICHMENT_PARTIAL",
    "unavailable": "SOURCE_TIMEOUT",
}


def sanitize_result(value: Any, *, policy: SanitizationPolicy, path: tuple[str, ...] = ()) -> Any:
    if len(path) > policy.max_depth:
        return "[REDACTED:MAX_DEPTH]"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): sanitize_result(item, policy=policy, path=(*path, str(key)))
            for key, item in value.items()
            if not _forbidden_key(key)
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_result(item, policy=policy, path=(*path, str(index))) for index, item in enumerate(value)]
    if isinstance(value, str):
        if _UUID_RE.match(value) and not value.startswith(("mcpref_", "mcpact_")):
            return "[REDACTED:INTERNAL_REFERENCE]"
        return sanitize_text(value, allow_operational_content=path in policy.trusted_operational_paths)
    return value


def _json_safe(value: Any) -> Any:
    """Compatibility wrapper using the strict default policy."""
    return sanitize_result(value, policy=SanitizationPolicy())


def _compact(value: Any, *, text_limit: int, list_limit: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= text_limit else value[:text_limit] + "…"
    if isinstance(value, dict):
        return {str(key): _compact(item, text_limit=text_limit, list_limit=list_limit) for key, item in list(value.items())[:16]}
    if isinstance(value, (list, tuple, set)):
        return [_compact(item, text_limit=text_limit, list_limit=list_limit) for item in list(value)[:list_limit]]
    return value


def _trim(value: Any, budget: int) -> Any:
    """Reduce fields, excerpts, then rows in the documented order."""
    if len(json.dumps(value, ensure_ascii=False, default=str).encode()) <= budget:
        return value
    for text_limit, list_limit in ((1_200, 10), (400, 5), (160, 1)):
        compact = _compact(value, text_limit=text_limit, list_limit=list_limit)
        if len(json.dumps(compact, ensure_ascii=False, default=str).encode()) <= budget:
            return compact
    return {"notice": "Output exceeded the safe response limit. Use the continuation cursor or narrower fields."}


def envelope(
    *,
    result: dict,
    request_id: str,
    summary: str,
    data: dict | None = None,
    sources: list[dict] | None = None,
    next_cursor: str | None = None,
    sanitization_policy: SanitizationPolicy | None = None,
) -> dict:
    status = result.get("status", "unavailable")
    warnings = list(result.get("warnings", []))
    if not warnings and status in DEFAULT_STATUS_CODE:
        warnings = [DEFAULT_STATUS_CODE[status]]
    policy = sanitization_policy or SanitizationPolicy()
    body = sanitize_result(data if data is not None else result.get("data", {}), policy=policy)
    page = {"next_cursor": next_cursor, "returned": len(body.get("items", [])) if isinstance(body, dict) and isinstance(body.get("items"), list) else 0}
    output = {
        "status": status,
        "summary": summary,
        "data": body,
        "sources": sanitize_result(sources if sources is not None else [], policy=policy),
        "page": page,
        "warnings": warnings,
        "request_id": request_id,
    }
    if len(json.dumps(output, ensure_ascii=False, default=str).encode()) > MAX_RESULT_BYTES:
        output["data"] = _trim(output["data"], MAX_RESULT_BYTES // 2)
        output["sources"] = _compact(output["sources"], text_limit=160, list_limit=5)
        output["status"] = "partial" if output["status"] == "ok" else output["status"]
        output["warnings"] = [*output["warnings"], "OUTPUT_TRUNCATED"]
    if len(json.dumps(output, ensure_ascii=False, default=str).encode()) > MAX_RESULT_BYTES:
        output["data"] = {"notice": "Output exceeded the safe response limit. Narrow the query and retry."}
        output["sources"] = []
        output["status"] = "partial" if output["status"] == "ok" else output["status"]
        output["warnings"] = list(dict.fromkeys([*output["warnings"], "OUTPUT_TRUNCATED"]))
    return output
