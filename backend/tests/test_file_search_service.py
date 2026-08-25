import asyncio

import pytest

from app.core.config import settings
from app.models.models import CompanyLibraryItem, KnowledgeChunk, KnowledgeDocument, ResourceGrant, ResourcePolicy, TeamMember, ProjectMember
from app.services.file_search_service import (
    FileSearchPrincipal,
    FileSearchServiceError,
    can_read_policy,
    compact_search_text,
    concept_groups_for_query,
    metadata_score,
    normalize_search_text,
    search_files,
    synonym_groups,
)


def _file(name: str, *, title: str | None = None, content_type: str = "application/octet-stream", extension: str | None = None, metadata: dict | None = None) -> CompanyLibraryItem:
    return CompanyLibraryItem(
        id=1,
        organization_id=1,
        kind="file",
        name=name,
        title=title,
        extension=extension,
        searchable_metadata=metadata or {},
        content_type=content_type,
        size=42,
        checksum="checksum",
        parent_id=None,
        deleted_at=None,
    )


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _SearchDb:
    def __init__(self, items, documents=None, chunks=None, policy=None, grants=None, fail_index=False):
        self.items = items
        self.documents = documents or []
        self.chunks = chunks or []
        self.policy = policy
        self.grants = grants or []
        self.fail_index = fail_index

    @staticmethod
    def _entity(statement):
        descriptions = getattr(statement, "column_descriptions", [])
        return descriptions[0].get("entity") if descriptions else None

    async def execute(self, statement):
        entity = self._entity(statement)
        if self.fail_index and entity is KnowledgeDocument:
            raise RuntimeError("index unavailable")
        if entity is CompanyLibraryItem:
            return _Rows(self.items)
        if entity is KnowledgeDocument:
            return _Rows(self.documents)
        if entity is KnowledgeChunk:
            return _Rows(self.chunks)
        if entity is ResourceGrant:
            return _Rows(self.grants)
        if entity in {TeamMember, ProjectMember}:
            return _Rows([])
        return _Rows([])

    async def scalar(self, statement):
        entity = self._entity(statement)
        if entity is ResourcePolicy:
            return self.policy
        return None


class _StorageFailureDb:
    async def execute(self, _statement):
        raise RuntimeError("database unavailable")


class _Request:
    operation = "search"
    search_mode = "keyword"
    folder_id = None
    file_types = []
    limit = 10
    delivery = "none"

    def __init__(self, query, delivery="none"):
        self.query = query
        self.delivery = delivery


def test_unicode_nfkc_casefold_and_separator_matching_are_shared():
    assert normalize_search_text(" ＴＥＭＰＬＡＴＥ ") == "template"
    assert compact_search_text("Quarterly_Report—2026") == "quarterlyreport2026"
    item = _file("Quarterly_Report—2026.PDF", title="Quarterly Report 2026", content_type="application/pdf")
    score, fields = metadata_score(item, "quarterly report 2026")
    assert score >= 1000
    assert "filename" in fields or "title" in fields


def test_partial_mime_extension_and_searchable_metadata_matching():
    item = _file("финансы.xlsx", title="Annual finance", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", metadata={"department": "Finance archive"})
    assert metadata_score(item, "finan")[0] > 0
    assert metadata_score(item, "spreadsheet")[0] > 0
    assert metadata_score(item, "archive")[0] > 0


@pytest.mark.parametrize("query", ["presentation template", "презентация шаблон", "презентаци загвар"])
def test_multilingual_concepts_are_general_metadata_groups(query):
    groups = concept_groups_for_query(query)
    assert "presentation" in groups
    assert "template" in groups
    item = _file("brand-kit.pptx", content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
    assert metadata_score(item, query)[0] > 0


def test_synonym_groups_can_be_configured_without_filename_rules(monkeypatch):
    monkeypatch.setattr(settings, "FILE_SEARCH_SYNONYMS_JSON", '{"deck_concept": ["pitchbook"]}')
    assert "deck_concept" in synonym_groups()
    assert "deck_concept" in concept_groups_for_query("pitchbook")


def test_pending_failed_and_image_only_files_remain_metadata_searchable():
    item = _file("Scanned_Deck.PPTX", content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
    principal = FileSearchPrincipal(organization_id=1, account_id=None, employee_id=7, channel="telegram")

    pending = asyncio.run(search_files(_SearchDb([item]), principal, _Request("scanned deck")))
    assert pending["status"] == "indexing"
    assert pending["data"]["results"][0]["content_state"] == "indexing"

    failed_doc = KnowledgeDocument(id=3, organization_id=1, source_type="company_file", source_id=1, title=item.name, index_status="failed", content_available=False)
    failed = asyncio.run(search_files(_SearchDb([item], documents=[failed_doc]), principal, _Request("scanned deck")))
    assert failed["status"] == "partial"
    assert failed["data"]["results"][0]["content_state"] == "failed"

    image_doc = KnowledgeDocument(id=4, organization_id=1, source_type="company_file", source_id=1, title=item.name, index_status="ready", content_available=False)
    image_only = asyncio.run(search_files(_SearchDb([item], documents=[image_doc]), principal, _Request("scanned deck")))
    assert image_only["status"] == "ok"
    assert image_only["data"]["results"][0]["content_state"] == "empty"


def test_acl_allowed_and_denied_and_attachment_delivery():
    item = _file("restricted-plan.pdf", content_type="application/pdf")
    policy = ResourcePolicy(id=8, organization_id=1, resource_type="company_file", resource_id=1, classification="restricted")
    principal = FileSearchPrincipal(organization_id=1, account_id=4, employee_id=7, roles=frozenset({"member"}))
    denied = asyncio.run(search_files(_SearchDb([item], policy=policy), principal, _Request("restricted plan")))
    assert denied["status"] == "empty"
    grant = ResourceGrant(policy_id=8, principal_type="account", principal_key="4")
    allowed = asyncio.run(search_files(_SearchDb([item], policy=policy, grants=[grant]), principal, _Request("restricted plan", delivery="attachment")))
    assert allowed["status"] == "indexing"
    assert allowed["deliveries"][0]["kind"] == "company_file_attachment"


def test_authoritative_database_failure_is_not_not_found():
    principal = FileSearchPrincipal(organization_id=1)
    with pytest.raises(FileSearchServiceError):
        asyncio.run(search_files(_StorageFailureDb(), principal, _Request("anything")))

    item = _file("does-not-match.pdf")
    unavailable_index = asyncio.run(search_files(_SearchDb([item], fail_index=True), principal, _Request("missing name")))
    assert unavailable_index["status"] == "unavailable"
