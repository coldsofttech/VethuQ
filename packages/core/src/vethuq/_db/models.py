"""SQLAlchemy models: the database schema."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class _Base(DeclarativeBase):
    pass


class _Source(_Base):
    """A file or folder the user has registered as input for OCR and indexing."""

    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("source_type IN ('file', 'folder')", name="ck_sources_source_type"),
        CheckConstraint(
            "status IN ('pending', 'indexed', 'error', 'removed')", name="ck_sources_status"
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default="pending"
    )
    added_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_scanned_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    removed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Comma-separated language ids the source is read in (`en,te`); NULL means the global
    # `ocr_languages` setting applies.
    languages: Mapped[str | None] = mapped_column(Text, nullable=True)
