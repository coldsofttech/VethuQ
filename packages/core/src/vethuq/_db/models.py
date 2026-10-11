"""SQLAlchemy models: the database schema."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from vethuq._db.values import _PageSource, _PassSource, _PassStatus
from vethuq.enums import FileStatus, IndexRunStatus, SourceStatus, SourceType


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
    # Progress, kept up to date as its files change state (see `_Documents.refresh_source`):
    # the files that count (not unsupported or removed) and how many of them are processed.
    files_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    files_processed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
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


class _Document(_Base):
    """One logical document: the files with the same content (SHA-256) share one row."""

    __tablename__ = "documents"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class _DocumentIndex(_Base):
    """One file of a source and where it is in indexing, by its absolute path.

    The earliest row (lowest id) of a document is its original; later ones are duplicates.
    """

    __tablename__ = "document_index"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Known once the file has been read and hashed.
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    file_path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[FileStatus] = mapped_column(
        _enum(FileStatus, "ck_document_index_status"),
        nullable=False,
        default=FileStatus.PENDING,
        server_default=FileStatus.PENDING.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The file as it was when last seen; a different size or time on disk means it was modified.
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    modified_at: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    removed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class _PdfPage(_Base):
    """One page of a PDF document: its text, whichever way it was produced.

    Pages belong to the logical document, so files with the same content share them.
    """

    __tablename__ = "pdf_pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_pdf_pages_document_page"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[_PageSource] = mapped_column(
        _enum(_PageSource, "ck_pdf_pages_source"), nullable=False
    )
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)


class _PdfPageQuick(_Base):
    """The quick OCR read of a PDF page in one language. Native pages have none."""

    __tablename__ = "pdf_pages_quick"
    __table_args__ = (
        UniqueConstraint("page_id", "language_id", name="uq_pdf_pages_quick_page_language"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), nullable=False
    )
    language_id: Mapped[int] = mapped_column(ForeignKey("languages.id"), nullable=False)
    # The images read on a mixed page; 0 when the whole page was read.
    region_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    engine: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[str] = mapped_column(Text, nullable=False)


class _DocumentLanguage(_Base):
    """A language a document was read in, and how that read went."""

    __tablename__ = "document_languages"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    language_id: Mapped[int] = mapped_column(ForeignKey("languages.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[_PassStatus] = mapped_column(
        _enum(_PassStatus, "ck_document_languages_status"),
        nullable=False,
        default=_PassStatus.PENDING,
    )
    source: Mapped[_PassSource] = mapped_column(
        _enum(_PassSource, "ck_document_languages_source"),
        nullable=False,
        default=_PassSource.DEFAULT,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class _IndexRun(_Base):
    """One run of the indexer. A run of one source (or one file of it) goes with that source."""

    __tablename__ = "index_runs"
    __table_args__ = (
        # Only one run can be going at a time.
        Index(
            "uq_index_runs_running",
            text("1"),
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=True, index=True
    )
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[IndexRunStatus] = mapped_column(
        _enum(IndexRunStatus, "ck_index_runs_status"),
        nullable=False,
        default=IndexRunStatus.RUNNING,
    )
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
