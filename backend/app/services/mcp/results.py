"""Bounded, redacted result envelopes returned by every MCP tool."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

MAX_RESULT_BYTES = 32 * 1024
FORBIDDEN_KEYS = frozenset({
    "token", "token_hash", "storage_key", "telegram_id", "encrypted_payload",
    "password", "password_hash", "access_token", "refresh_token", "raw_id",
})


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
    "unavailable": "SOURCE_TIMEOUT",
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
            if not _forbidden_key(key)
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


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
) -> dict:
    status = result.get("status", "unavailable")
    warnings = list(result.get("warnings", []))
    if not warnings and status in DEFAULT_STATUS_CODE:
        warnings = [DEFAULT_STATUS_CODE[status]]
    body = _json_safe(data if data is not None else result.get("data", {}))
    page = {"next_cursor": next_cursor, "returned": len(body.get("items", [])) if isinstance(body, dict) and isinstance(body.get("items"), list) else 0}
    output = {
        "status": status,
        "summary": summary,
        "data": body,
        "sources": _json_safe(sources if sources is not None else []),
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
