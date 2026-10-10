"""SQLAlchemy models: the database schema."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class _Base(DeclarativeBase):
    pass


class _Language(_Base):
    """A language VethuQ can read documents in (`en`, `te`, ...). English is seeded."""

    __tablename__ = "languages"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    language: Mapped[str] = mapped_column(Text, unique=True, nullable=False)


class _SourceLanguage(_Base):
    """A language a source is read in."""

    __tablename__ = "source_languages"

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    language_id: Mapped[int] = mapped_column(ForeignKey("languages.id"), primary_key=True)
    language: Mapped[_Language] = relationship(lazy="joined")


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
    # The languages the source is read in; none means the global `ocr_languages` setting applies.
    language_links: Mapped[list[_SourceLanguage]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="_SourceLanguage.language_id",
    )

    @property
    def language_codes(self) -> list[str]:
        """The ids of the languages the source is read in (`["en", "te"]`), in language order."""
        return [link.language.language for link in self.language_links]
