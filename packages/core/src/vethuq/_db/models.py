"""SQLAlchemy models: the database schema."""

from __future__ import annotations

from enum import StrEnum
from sqlalchemy import Boolean, Enum, ForeignKey, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from vethuq.enums import SourceStatus, SourceType


def _enum(enum_class: type[StrEnum], name: str) -> Enum:
    """A text column holding the enum's values, with a CHECK constraint on them."""
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=16,
        values_callable=lambda members: [member.value for member in members],
    )


class _Base(DeclarativeBase):
    pass


class _SchemaVersion(_Base):
    """The version of the database schema; the table holds a single row."""

    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)


class _Setting(_Base):
    """A named setting and its saved value; a setting with no row uses its default."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


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
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        _enum(SourceType, "ck_sources_source_type"), nullable=False
    )
    status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus, "ck_sources_status"),
        nullable=False,
        default=SourceStatus.PENDING,
        server_default=SourceStatus.PENDING.value,
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
