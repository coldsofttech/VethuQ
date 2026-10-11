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

from vethuq._db.values import (
    _GrantKind,
    _JobPageState,
    _LedgerKind,
    _PageSource,
    _PageState,
    _PassSource,
    _PassStatus,
)
from vethuq.enums import FileStatus, IndexRunStatus, RemoteJobStatus, SourceStatus, SourceType


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
    # Why it failed, as a short code (see `_ErrorCode`), for statistics.
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # For a page whose text is all native but that has pictures the quick phase left alone (a
    # Markdown file's): the phase (`moderate`) from which they are read. NULL otherwise.
    deepen_from: Mapped[str | None] = mapped_column(Text, nullable=True)
    # While the file's language is being judged (several candidate languages): what OCR read, line
    # by line with its score (JSON), so the lines the first language made up can be dropped.
    read_lines: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `done` once its text is final; a page whose OCR is still to come (or away) says so.
    status: Mapped[_PageState] = mapped_column(
        _enum(_PageState, "ck_pdf_pages_status"),
        nullable=False,
        default=_PageState.DONE,
        server_default=_PageState.DONE.value,
    )


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


class _TxtPage(_Base):
    """What a plain-text file's type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "txt_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    encoding: Mapped[str | None] = mapped_column(Text, nullable=True)


class _CsvPage(_Base):
    """What the CSV type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "csv_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    encoding: Mapped[str | None] = mapped_column(Text, nullable=True)
    delimiter: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # non-empty rows
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # widest row


class _MarkdownPage(_Base):
    """What the Markdown type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "markdown_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    encoding: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # local images linked


class _HtmlPage(_Base):
    """What the HTML type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "html_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    encoding: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    lang: Mapped[str | None] = mapped_column(Text, nullable=True)  # `<html lang>`
    link_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # local pictures used


class _XmlPage(_Base):
    """What the XML type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "xml_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    encoding: Mapped[str | None] = mapped_column(Text, nullable=True)
    root: Mapped[str | None] = mapped_column(Text, nullable=True)  # the root element's name
    element_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attribute_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    well_formed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class _CssPage(_Base):
    """What the CSS type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "css_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    encoding: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # local pictures used


class _JsPage(_Base):
    """What the JavaScript type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "js_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    encoding: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # non-empty lines
    comment_lines: Mapped[int | None] = mapped_column(Integer, nullable=True)


class _JsonPage(_Base):
    """What the JSON type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "json_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    encoding: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str | None] = mapped_column(Text, nullable=True)  # object, array or scalar
    value_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # leaves flattened
    max_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)


class _YamlPage(_Base):
    """What the YAML type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "yaml_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    encoding: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # `---` documents
    value_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # leaves flattened
    max_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)


class _DocxPage(_Base):
    """What the Word (.docx) type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "docx_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    line_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # non-empty lines
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # embedded pictures


class _DocPage(_Base):
    """What the Word (.doc) type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "doc_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    line_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # non-empty lines
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # embedded pictures


class _XlsxPage(_Base):
    """What the Excel (.xlsx) type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "xlsx_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    line_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # non-empty lines
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # embedded pictures


class _XlsPage(_Base):
    """What the Excel (.xls) type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "xls_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    line_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # non-empty lines
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # embedded pictures


class _PptxPage(_Base):
    """What the PowerPoint (.pptx) type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "pptx_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    line_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # non-empty lines
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # embedded pictures


class _PptPage(_Base):
    """What the PowerPoint (.ppt) type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "ppt_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    line_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # non-empty lines
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # embedded pictures


class _RtfPage(_Base):
    """What the RTF type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "rtf_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    line_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # non-empty lines
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # embedded pictures


class _EmlPage(_Base):
    """What the email type keeps about its page, beside the text in `pdf_pages`."""

    __tablename__ = "eml_pages"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender: Mapped[str | None] = mapped_column(Text, nullable=True)
    recipients_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    recipients_cc: Mapped[str | None] = mapped_column(Text, nullable=True)
    recipients_bcc: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[str | None] = mapped_column(Text, nullable=True)  # ISO 8601
    message_id: Mapped[str | None] = mapped_column(Text, nullable=True)


class _PdfPagePhase(_Base):
    """A deeper OCR phase (`moderate`, `deep`) read on a page in one language: the angles it read.
    The quick read of a page is `pdf_pages_quick`."""

    __tablename__ = "pdf_pages_phases"
    __table_args__ = (
        UniqueConstraint(
            "page_id", "language_id", "phase", name="uq_pdf_pages_phases_page_language_phase"
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), nullable=False
    )
    language_id: Mapped[int] = mapped_column(ForeignKey("languages.id"), nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    # The angles read, comma separated; and the images they were read from (1 for a scanned page).
    angles: Mapped[str] = mapped_column(Text, nullable=False, default="")
    region_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # What the phase added to the page's text.
    lines_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    engine: Mapped[str] = mapped_column(Text, nullable=False, default="")
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
    # On the first language's row: the languages the file may be read in (their ids, comma
    # separated, the first one first, e.g. `en,te`), kept until the first read has been judged.
    candidates: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


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
    # The processing tier it ran with.
    tier: Mapped[str] = mapped_column(Text, nullable=False, default="local", server_default="local")
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Pages read in this run, how many of them needed OCR, and the credits that cost.
    processed_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ocr_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credits_milli: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # How the run was asked for: `run`, `restart` (failed files only), `reindex` (every file under
    # the target, read again) or `file` (one file, read again).
    mode: Mapped[str] = mapped_column(Text, nullable=False, default="run", server_default="run")
    # What the caller asks of the run: `run`, `pause` or `stop`. Workers look at it between files,
    # pages and angle passes, so it works from another thread or process.
    control: Mapped[str] = mapped_column(Text, nullable=False, default="run", server_default="run")
    # Where the run is: the OCR phase it is working on, the files being read right now (a JSON list
    # of paths), how many workers are active, and how many pages the deeper phases have read.
    phase: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    current_files: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]"
    )
    workers_active: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    deepened_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Files under the target that no installed add-on reads (found when the run looked at the disk).
    unsupported_files: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class _CreditGrant(_Base):
    """Credits a wallet received: its daily allowance, a starter, a licence grant, a promotion.

    `remaining_milli` is what is left (credits are whole milli-credits). Daily and promotional
    grants expire at the end of their UTC day; a grant with `scope` is spent only on that
    add-on's work. `ref` makes granting repeatable: a wallet gets each `ref` once.
    """

    __tablename__ = "credit_grants"
    __table_args__ = (
        UniqueConstraint("wallet", "ref", name="uq_credit_grants_wallet_ref"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet: Mapped[str] = mapped_column(Text, nullable=False, default="local")
    kind: Mapped[_GrantKind] = mapped_column(_enum(_GrantKind, "ck_credit_grants_kind"))
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref: Mapped[str] = mapped_column(Text, nullable=False)
    amount_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    granted_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class _CreditLedger(_Base):
    """One movement of credits. A charge that spans several grants has a row for each."""

    __tablename__ = "credit_ledger"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    wallet: Mapped[str] = mapped_column(Text, nullable=False, default="local")
    kind: Mapped[_LedgerKind] = mapped_column(_enum(_LedgerKind, "ck_credit_ledger_kind"))
    amount_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    grant_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_grants.id", ondelete="SET NULL"), nullable=True
    )
    # What the credits were for. Deleted with the source (the balance lives in the grants).
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=True, index=True
    )
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phase: Mapped[str | None] = mapped_column(Text, nullable=True)
    angle: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_factor_milli: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_card_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class _UsageDaily(_Base):
    """What was processed on a UTC day, summed. No names, paths or text: this is what statistics
    show and what metrics sharing sends (without `source_id`, which stays on this computer)."""

    __tablename__ = "usage_daily"
    __table_args__ = (
        Index(
            "uq_usage_daily_key",
            "day",
            text("coalesce(source_id, 0)"),
            "file_type",
            "phase",
            "language",
            "engine",
            "page_source",
            "size_bucket",
            "band",
            unique=True,
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # Kept when its source is purged (statistics stay); then it is NULL.
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    file_type: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)  # "" for a native page
    language: Mapped[str] = mapped_column(Text, nullable=False)
    engine: Mapped[str] = mapped_column(Text, nullable=False)  # "" for a native page
    page_source: Mapped[str] = mapped_column(Text, nullable=False)
    size_bucket: Mapped[str] = mapped_column(Text, nullable=False)
    band: Mapped[str] = mapped_column(Text, nullable=False)
    pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    credits_milli: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class _FileFootprint(_Base):
    """What reading one file took (no name or path): the history a worker scheduler plans from."""

    __tablename__ = "file_footprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recorded_at: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    pages: Mapped[int] = mapped_column(Integer, nullable=False)
    seconds: Mapped[float] = mapped_column(Float, nullable=False)
    workers: Mapped[int] = mapped_column(Integer, nullable=False)


class _UsageFailure(_Base):
    """Files that failed on a UTC day, by reason code."""

    __tablename__ = "usage_failures"
    __table_args__ = (
        Index(
            "uq_usage_failures_key",
            "day",
            text("coalesce(source_id, 0)"),
            "file_type",
            "code",
            unique=True,
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    file_type: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class _RemoteJob(_Base):
    """A batch of images sent to a remote processing tier, and where it is."""

    __tablename__ = "remote_jobs"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("index_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    wallet: Mapped[str] = mapped_column(Text, nullable=False)
    # What the tier gave back for the batch; it must stay valid across restarts.
    handle: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RemoteJobStatus] = mapped_column(
        _enum(RemoteJobStatus, "ck_remote_jobs_status"),
        nullable=False,
        default=RemoteJobStatus.SUBMITTED,
    )
    images: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credits_milli: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    submitted_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class _RemoteJobPage(_Base):
    """One image of a page that needs remote OCR. It is paid for when it is staged; it belongs to
    a job once the job is sent."""

    __tablename__ = "remote_job_pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_number", "region", "language_id", "phase", "angle",
                         name="uq_remote_job_pages_image"),
        {"sqlite_autoincrement": True},
    )  # fmt: skip

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("remote_jobs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    region: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    language_id: Mapped[int] = mapped_column(ForeignKey("languages.id"), nullable=False)
    # The OCR phase asking, and the angle the image is read at (see `OcrRequest`).
    phase: Mapped[str] = mapped_column(
        Text, nullable=False, default="quick", server_default="quick"
    )
    angle: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    request_key: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[_JobPageState] = mapped_column(
        _enum(_JobPageState, "ck_remote_job_pages_state"),
        nullable=False,
        default=_JobPageState.STAGED,
    )
    size_factor_milli: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    credits_milli: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The ledger rows that paid for it, to give back if it never comes back.
    ledger_ids: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The run that staged it, and the wallet that paid.
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wallet: Mapped[str] = mapped_column(Text, nullable=False, default="local")


class _PageSearch(_Base):
    """A page's text in the coarsest form the installed search normalizers allow: what the search
    index (`page_search_fts`) is built over. A page whose text changes loses its row (a trigger),
    and gets a new one the next time the index is brought up to date."""

    __tablename__ = "page_search"

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_pages.id", ondelete="CASCADE"), primary_key=True
    )
    norm_text: Mapped[str] = mapped_column(Text, nullable=False)
