"""Authoritative, tenant-scoped company-file discovery and authorization.

The storage row is the discovery boundary.  Knowledge documents and chunks are
an optional enrichment layer: they can add excerpts and semantic relevance,
but they are never allowed to hide a file whose metadata matches the query.
"""

from __future__ import annotations

import re
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import (
    CompanyKnowledge,
    CompanyLibraryItem,
    KnowledgeChunk,
    KnowledgeDocument,
    ProjectMember,
    ResourceGrant,
    ResourcePolicy,
    TeamMember,
)


FileSearchStatus = Literal["ok", "empty", "indexing", "partial", "denied", "unavailable"]


@dataclass(frozen=True)
class FileSearchPrincipal:
    """The minimum trusted identity needed by company-file authorization.

    ``account_id`` is intentionally optional.  A verified Telegram employee
    can discover normal internal company files before a workspace account is
    provisioned; account grants still cannot be satisfied by that principal.
    """

    organization_id: int
    account_id: int | None = None
    employee_id: int | None = None
    roles: frozenset[str] = frozenset()
    channel: str = "web"
    locale: str = "en"
    telegram_id: str | None = None

    @classmethod
    def from_actor(cls, actor: Any) -> "FileSearchPrincipal":
        return cls(
            organization_id=int(actor.organization_id),
            account_id=getattr(actor, "account_id", None),
            employee_id=getattr(actor, "employee_id", None),
            roles=frozenset(getattr(actor, "roles", frozenset())),
            channel=getattr(actor, "channel", "web"),
            locale=getattr(actor, "locale", "en"),
        )


class FileSearchServiceError(RuntimeError):
    """Raised when the authoritative storage or policy service is unavailable."""


# This is a configurable concept vocabulary, not a filename or phrase rule.
# Deployments can extend it without changing search code.  Terms are matched
# by normalized token/prefix, so inflected Unicode forms participate naturally.
DEFAULT_SYNONYM_GROUPS: dict[str, frozenset[str]] = {
    "presentation": frozenset({
        "presentation", "presentations", "slide", "slides", "deck",
        "презентация", "презентаци", "танилцуулга", "танилцуулгын",
    }),
    "template": frozenset({
        "template", "templates", "шаблон", "загвар", "загварын",
    }),
    "document": frozenset({"document", "documents", "doc", "баримт", "файл"}),
}

_PRESENTATION_EXTENSIONS = frozenset({"ppt", "pptx", "pot", "potx", "potm", "odp"})
_TEMPLATE_EXTENSIONS = frozenset({"pot", "potx", "potm", "otp"})
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def synonym_groups() -> dict[str, frozenset[str]]:
    """Load deploy-configured concepts while retaining safe built-in defaults."""
    raw = str(getattr(settings, "FILE_SEARCH_SYNONYMS_JSON", "") or "").strip()
    if not raw:
        return DEFAULT_SYNONYM_GROUPS
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return DEFAULT_SYNONYM_GROUPS
        configured = {
            str(group): frozenset(str(alias) for alias in aliases if str(alias).strip())
            for group, aliases in payload.items()
            if isinstance(aliases, (list, tuple, set)) and aliases
        }
        return configured or DEFAULT_SYNONYM_GROUPS
    except (TypeError, ValueError, json.JSONDecodeError):
        return DEFAULT_SYNONYM_GROUPS


def normalize_search_text(value: str | None) -> str:
    """Normalize Unicode, case, and compatibility forms for comparisons."""
    return unicodedata.normalize("NFKC", value or "").casefold().strip()


def search_tokens(value: str | None) -> list[str]:
    return _TOKEN_RE.findall(normalize_search_text(value))


def compact_search_text(value: str | None) -> str:
    """Remove separators/punctuation while preserving Unicode letters/digits."""
    return "".join(char for char in normalize_search_text(value) if char.isalnum())


def _alias_matches(token: str, alias: str) -> bool:
    token = compact_search_text(token)
    alias = compact_search_text(alias)
    if not token or not alias:
        return False
    return token == alias or len(token) >= 3 and (alias.startswith(token) or token.startswith(alias))


def concept_groups_for_query(query: str) -> set[str]:
    groups: set[str] = set()
    configured_groups = synonym_groups()
    for token in search_tokens(query):
        for group, aliases in configured_groups.items():
            if any(_alias_matches(token, alias) for alias in aliases):
                groups.add(group)
    return groups


def is_file_search_query(query: str | None) -> bool:
    """Shared lightweight intent signal used by deterministic gateway fallbacks."""
    tokens = {compact_search_text(token) for token in search_tokens(query)}
    if not tokens:
        return False
    file_words = {
        "file", "files", "document", "documents", "attachment", "download",
        "ppt", "pptx", "pdf", "doc", "docx", "xlsx", "csv", "файл", "баримт",
        "презентация", "презентаци", "танилцуулга", "загвар", "template", "шаблон",
    }
    return any(any(_alias_matches(token, word) for word in file_words) for token in tokens)


def _result(
    status: FileSearchStatus,
    data: dict[str, Any] | None = None,
    *,
    sources: list[dict] | None = None,
    deliveries: list[dict] | None = None,
    warnings: list[str] | None = None,
    diagnostics: list[dict] | None = None,
) -> dict:
    return {
        "status": status,
        "data": data or {},
        "sources": sources or [],
        "deliveries": deliveries or [],
        "warnings": warnings or [],
        "diagnostics": diagnostics or [],
    }


async def policy_for_item(db: AsyncSession, item: CompanyLibraryItem) -> ResourcePolicy | None:
    """Resolve the nearest inherited policy without crossing a tenant."""
    current: CompanyLibraryItem | None = item
    seen: set[int] = set()
    while current and current.id not in seen:
        seen.add(current.id)
        policy = await db.scalar(select(ResourcePolicy).where(
            ResourcePolicy.organization_id == item.organization_id,
            ResourcePolicy.resource_type == "company_file",
            ResourcePolicy.resource_id == current.id,
        ))
        if policy and (current.id == item.id or policy.inherit_from_parent):
            return policy
        if not current.parent_id:
            break
        current = await db.scalar(select(CompanyLibraryItem).where(
            CompanyLibraryItem.organization_id == item.organization_id,
            CompanyLibraryItem.id == current.parent_id,
        ))
    return None


async def can_read_policy(db: AsyncSession, principal: FileSearchPrincipal, policy: ResourcePolicy | None) -> bool:
    if policy is None or policy.classification in {"internal", "public_link_safe"}:
        return True
    if "admin" in principal.roles or policy.classification == "confidential" and "manager" in principal.roles:
        return True
    grants = list((await db.execute(select(ResourceGrant).where(ResourceGrant.policy_id == policy.id))).scalars().all())
    team_ids = set((await db.execute(select(TeamMember.team_id).where(TeamMember.employee_id == principal.employee_id))).scalars().all()) if principal.employee_id else set()
    project_ids = set((await db.execute(select(ProjectMember.project_id).where(ProjectMember.employee_id == principal.employee_id))).scalars().all()) if principal.employee_id else set()
    for grant in grants:
        if grant.principal_type == "account" and principal.account_id is not None and grant.principal_key == str(principal.account_id):
            return True
        if grant.principal_type == "role" and grant.principal_key in principal.roles:
            return True
        if grant.principal_type == "team" and grant.principal_key.isdigit() and int(grant.principal_key) in team_ids:
            return True
        if grant.principal_type == "project" and grant.principal_key.isdigit() and int(grant.principal_key) in project_ids:
            return True
    # Restricted resources deliberately require a matching grant.  The same
    # grant loop above also permits team/project/role grants when configured.
    return False


def _extension(item: CompanyLibraryItem) -> str:
    value = getattr(item, "extension", None) or Path(item.name or "").suffix
    return str(value or "").casefold().lstrip(".")


def _title(item: CompanyLibraryItem) -> str:
    return str(getattr(item, "title", None) or item.name or "")


def _metadata_blob(item: CompanyLibraryItem) -> str:
    metadata = getattr(item, "searchable_metadata", None) or {}
    if isinstance(metadata, dict):
        return " ".join(f"{key} {value}" for key, value in metadata.items())
    return str(metadata)


def _metadata_concepts(item: CompanyLibraryItem) -> set[str]:
    extension = _extension(item)
    content_type = normalize_search_text(getattr(item, "content_type", None))
    concepts: set[str] = set()
    if extension in _PRESENTATION_EXTENSIONS or "presentation" in content_type or "powerpoint" in content_type:
        concepts.add("presentation")
    if extension in _TEMPLATE_EXTENSIONS or "template" in content_type:
        concepts.add("template")
    if item.kind == "file":
        concepts.add("document")
    return concepts


def metadata_score(item: CompanyLibraryItem, query: str) -> tuple[float, list[str]]:
    """Score all authoritative metadata fields with separator-insensitive rules."""
    query_norm = normalize_search_text(query)
    query_compact = compact_search_text(query)
    query_parts = search_tokens(query)
    if not query_compact or not query_parts:
        return 0.0, []
    fields = {
        "filename": item.name or "",
        "title": _title(item),
        "extension": _extension(item),
        "mime_type": getattr(item, "content_type", None) or "",
        "metadata": _metadata_blob(item),
    }
    score = 0.0
    matched: list[str] = []
    for field, value in fields.items():
        value_norm = normalize_search_text(value)
        value_compact = compact_search_text(value)
        if query_norm == value_norm or query_compact == value_compact:
            score = max(score, 1000.0 if field in {"filename", "title"} else 700.0)
            matched.append(field)
        elif query_compact and query_compact in value_compact:
            score = max(score, 650.0 if field in {"filename", "title"} else 420.0)
            matched.append(field)
        value_concepts = concept_groups_for_query(value)
        token_hits = sum(
            1 for token in query_parts
            if compact_search_text(token) in value_compact
            or any(group in value_concepts for group, aliases in synonym_groups().items() if any(_alias_matches(token, alias) for alias in aliases))
        )
        if token_hits:
            score += token_hits * (80.0 if field in {"filename", "title"} else 35.0)
            if field not in matched:
                matched.append(field)

    query_concepts = concept_groups_for_query(query)
    item_concepts = _metadata_concepts(item)
    concept_hits = query_concepts.intersection(item_concepts)
    if concept_hits:
        score += 180.0 * len(concept_hits)
        matched.extend(f"concept:{concept}" for concept in sorted(concept_hits))
    return score, matched


def _content_score(content: str, query: str) -> float:
    haystack = compact_search_text(content)
    needle = compact_search_text(query)
    if not haystack or not needle:
        return 0.0
    if needle == haystack:
        return 700.0
    if needle in haystack:
        return 260.0
    return float(sum(35 for token in search_tokens(query) if compact_search_text(token) in haystack))


def _content_state(document: KnowledgeDocument | None, has_chunks: bool = False) -> str:
    if document is None or document.index_status in {"pending", "indexing"}:
        return "indexing"
    if document.index_status == "failed":
        return "failed"
    if document.index_status == "ready" and not (getattr(document, "content_available", False) or has_chunks):
        return "empty"
    return "ready"


def _delivery_rows(rows: list[dict], delivery: str) -> list[dict]:
    if delivery == "none":
        return []
    deliveries: list[dict] = []
    for row in rows:
        if row.get("kind") == "folder" or not str(row.get("source_id", "")).startswith("company_file:"):
            continue
        item_id = str(row["source_id"]).split(":", 1)[1]
        if delivery == "attachment":
            deliveries.append({
                "source_id": row["source_id"],
                "kind": "company_file_attachment",
                "item_id": int(item_id),
                "filename": row.get("title"),
                "content_type": row.get("content_type") or "application/octet-stream",
                "size": row.get("size"),
            })
        else:
            deliveries.append({
                "source_id": row["source_id"],
                "kind": "authenticated_link",
                "url": f"{settings.PUBLIC_APP_URL.rstrip('/')}/company-files?item={item_id}",
            })
    return deliveries


async def authorized_file(db: AsyncSession, principal: FileSearchPrincipal, item_id: int) -> tuple[CompanyLibraryItem, ResourcePolicy | None] | None:
    """Resolve a live file and re-check tenant, ancestry, and ACL at delivery time."""
    item = await db.scalar(select(CompanyLibraryItem).where(
        CompanyLibraryItem.id == item_id,
        CompanyLibraryItem.organization_id == principal.organization_id,
        CompanyLibraryItem.kind == "file",
        CompanyLibraryItem.deleted_at.is_(None),
    ))
    if not item:
        return None
    current = item
    seen: set[int] = set()
    while current.parent_id is not None:
        if current.id in seen:
            return None
        seen.add(current.id)
        current = await db.scalar(select(CompanyLibraryItem).where(
            CompanyLibraryItem.organization_id == principal.organization_id,
            CompanyLibraryItem.id == current.parent_id,
        ))
        if not current or current.deleted_at is not None:
            return None
    policy = await policy_for_item(db, item)
    if not await can_read_policy(db, principal, policy):
        return None
    return item, policy


async def search_files(db: AsyncSession, principal: FileSearchPrincipal, data: Any) -> dict:
    """Search storage metadata first and add optional knowledge enrichment."""
    if data.operation == "search" and not getattr(data, "query", None):
        return _result("denied", {"reason": "A search query is required."}, diagnostics=[{"code": "invalid_request"}])
    query = getattr(data, "query", None) or ""
    try:
        all_items = list((await db.execute(select(CompanyLibraryItem).where(
            CompanyLibraryItem.organization_id == principal.organization_id,
            CompanyLibraryItem.deleted_at.is_(None),
        ).order_by(CompanyLibraryItem.kind, CompanyLibraryItem.name))).scalars().all())
    except Exception as exc:
        raise FileSearchServiceError("authoritative company storage unavailable") from exc

    by_id = {item.id: item for item in all_items}
    if getattr(data, "folder_id", None) is not None:
        folder_id = data.folder_id
        if folder_id not in by_id or by_id[folder_id].kind != "folder":
            return _result("denied", {"reason": "Folder is not available."}, diagnostics=[{"code": "folder_denied"}])

        def in_folder(item: CompanyLibraryItem) -> bool:
            current_id = item.parent_id
            seen: set[int] = set()
            while current_id is not None and current_id not in seen:
                if current_id == folder_id:
                    return True
                seen.add(current_id)
                current_id = by_id.get(current_id).parent_id if by_id.get(current_id) else None
            return False
    else:
        in_folder = lambda item: True

    allowed_types = {str(value).casefold().lstrip(".") for value in (getattr(data, "file_types", None) or [])}
    visible: list[tuple[CompanyLibraryItem, str]] = []
    denied_count = 0
    try:
        for item in all_items:
            if not in_folder(item):
                continue
            if item.kind == "file" and allowed_types and _extension(item) not in allowed_types:
                continue
            policy = await policy_for_item(db, item)
            if not await can_read_policy(db, principal, policy):
                denied_count += 1
                continue
            visible.append((item, policy.classification if policy else "internal"))
    except Exception as exc:
        raise FileSearchServiceError("company-file authorization unavailable") from exc

    if data.operation == "list":
        rows = [{
            "source_id": f"company_file:{item.id}", "title": _title(item), "kind": item.kind,
            "parent_id": item.parent_id, "content_type": getattr(item, "content_type", None),
            "extension": _extension(item), "size": item.size,
            "classification": classification,
        } for item, classification in visible[:data.limit]]
        return _result("ok" if rows else "empty", {"query": query, "results": rows}, sources=[{"id": row["source_id"], "title": row["title"]} for row in rows], deliveries=_delivery_rows(rows, data.delivery))

    metadata_matches: dict[int, dict] = {}
    for item, classification in visible:
        if item.kind != "file":
            continue
        score, fields = metadata_score(item, query)
        if score > 0:
            metadata_matches[item.id] = {
                "source_id": f"company_file:{item.id}", "title": _title(item), "excerpt": "",
                "locator": {"kind": "metadata", "fields": fields}, "score": score,
                "classification": classification, "content_type": getattr(item, "content_type", None),
                "extension": _extension(item), "size": item.size, "kind": item.kind,
                "parent_id": item.parent_id,
            }

    warnings: list[str] = []
    diagnostics: list[dict] = []
    documents: dict[int, KnowledgeDocument] = {}
    chunks: list[KnowledgeChunk] = []
    index_unavailable = False
    try:
        docs = list((await db.execute(select(KnowledgeDocument).where(
            KnowledgeDocument.organization_id == principal.organization_id,
            KnowledgeDocument.source_type == "company_file",
        ))).scalars().all())
        documents = {document.source_id: document for document in docs if document.source_id in by_id}
        ready_ids = [document.id for document in docs if document.index_status == "ready"]
        if ready_ids:
            chunks = list((await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.document_id.in_(ready_ids)))).scalars().all())
    except Exception as exc:
        index_unavailable = True
        warnings.append("content_index_unavailable")
        diagnostics.append({"code": "content_index_unavailable", "detail": str(exc)[:160]})

    visible_ids = {item.id for item, _ in visible if item.kind == "file"}
    for chunk in chunks:
        document = next((doc for doc in documents.values() if doc.id == chunk.document_id), None)
        if not document or document.source_id not in visible_ids:
            continue
        score = _content_score(chunk.content, query)
        if score <= 0:
            continue
        row = metadata_matches.get(document.source_id)
        if row is None:
            item = by_id[document.source_id]
            classification = next(value for candidate, value in visible if candidate.id == item.id)
            row = {
                "source_id": f"company_file:{item.id}", "title": _title(item), "excerpt": "",
                "locator": {"kind": "content"}, "score": 0.0, "classification": classification,
                "content_type": getattr(item, "content_type", None), "extension": _extension(item),
                "size": item.size, "kind": item.kind, "parent_id": item.parent_id,
            }
            metadata_matches[item.id] = row
        if score > row["score"]:
            row["score"] = score
            row["excerpt"] = chunk.content[:900]
            row["locator"] = chunk.locator

    rows = []
    for item_id, row in sorted(metadata_matches.items(), key=lambda pair: (-pair[1]["score"], normalize_search_text(pair[1]["title"])))[:data.limit]:
        state = _content_state(documents.get(item_id), any(chunk.document_id == documents[item_id].id for chunk in chunks) if item_id in documents else False)
        row = {**row, "content_state": state}
        rows.append(row)

    if not rows:
        if index_unavailable:
            return _result("unavailable", {"query": query, "results": []}, warnings=warnings, diagnostics=diagnostics)
        return _result("empty", {"query": query, "results": []}, diagnostics=[{"code": "no_authorized_match", "denied_candidates": denied_count}])

    states = {row["content_state"] for row in rows}
    if any(state == "failed" for state in states) or index_unavailable:
        status: FileSearchStatus = "partial"
        warnings.append("metadata_match_content_enrichment_incomplete")
    elif states and states.issubset({"indexing"}):
        status = "indexing"
        diagnostics.append({"code": "metadata_match_indexing_pending"})
    else:
        status = "ok"
        if "empty" in states:
            diagnostics.append({"code": "metadata_match_without_extractable_content"})
    deliveries = _delivery_rows(rows, getattr(data, "delivery", "none"))
    return _result(status, {"query": query, "results": rows}, sources=[{"id": row["source_id"], "title": row["title"], "locator": row["locator"]} for row in rows], deliveries=deliveries, warnings=warnings, diagnostics=diagnostics)


async def list_authorized_items(db: AsyncSession, principal: FileSearchPrincipal, folder_id: int | None = None) -> list[CompanyLibraryItem]:
    """Common browser/archive listing helper with the same ACL semantics."""
    request = SimpleNamespace(
        operation="list", query=None, search_mode="keyword", file_types=[],
        limit=500, delivery="none", folder_id=folder_id,
    )
    result = await search_files(db, principal, request)
    ids = [int(row["source_id"].split(":", 1)[1]) for row in result["data"].get("results", [])]
    return [item for item_id in ids if (item := await db.get(CompanyLibraryItem, item_id))]
