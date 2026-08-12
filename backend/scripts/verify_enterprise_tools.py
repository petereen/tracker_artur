"""Production-shaped smoke verification for the enterprise assistant tool layer.

Run after `alembic upgrade head` with ENTERPRISE_TOOLS_ENABLED=true.  It makes
no writes: it checks required extensions/tables and validates strict contracts.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.enterprise_tools import FileSearchInput, tool_specs


async def main() -> None:
    expected_tools = {"file_search_tool", "get_stats_tool", "project_mgmt_tool", "project_mgmt_update_tool", "calendar_tool", "employee_directory_tool", "create_task", "delegate_task"}
    assert {item["name"] for item in tool_specs()} == expected_tools
    assert FileSearchInput(query="security policy").search_mode == "hybrid"
    async with AsyncSessionLocal() as db:
        extension = await db.scalar(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
        assert extension == "vector", "pgvector extension is missing; deploy the pgvector image and run migrations"
        tables = set((await db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))).scalars())
        required = {"resource_policies", "resource_grants", "knowledge_documents", "knowledge_chunks", "assistant_tool_audits", "assistant_pending_actions"}
        assert required.issubset(tables), f"missing tables: {sorted(required - tables)}"
    print("enterprise tool verification passed")


if __name__ == "__main__":
    asyncio.run(main())
