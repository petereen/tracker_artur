"""News & announcements published to the «Өнөөдөр» feed."""
from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import text as sa_text

from app.core.database import Base


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (
        CheckConstraint("status IN ('draft','published','archived')", name="ck_announcements_status"),
        Index("ix_announcements_org_feed", "organization_id", "status", "is_pinned", "published_at"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    summary = Column(Text)
    # Markdown.
    body = Column(Text, nullable=False, server_default="", default="")
    cover_url = Column(Text)
    image_urls = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    category = Column(Text)
    is_pinned = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    status = Column(Text, nullable=False, server_default="draft", default="draft")
    # Set on the first publication and kept when a post is edited later.
    published_at = Column(DateTime(timezone=True))
    author_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    # Snapshot, so the byline survives the author's account.
    author_name = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
