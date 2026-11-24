"""Concept graph: links between related chapters across books/grades (Phase 4).

Example: a Physics grade-10 chapter on forces "same_concept" a grade-12 chapter on
Newton's laws. Links are admin-curated knowledge-base data.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CONCEPT_RELATIONS: tuple[str, ...] = ("same_concept", "prerequisite", "related")


class ConceptLink(Base):
    __tablename__ = "concept_links"
    __table_args__ = (
        UniqueConstraint(
            "source_book_id", "source_chapter", "target_book_id", "target_chapter",
            name="uq_concept_links_pair",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    source_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    target_book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    target_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    relation: Mapped[str] = mapped_column(String(32), nullable=False, default="related")
    label_fa: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
