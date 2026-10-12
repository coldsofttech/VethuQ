"""The search index: each page's text in the coarsest form the installed normalizers allow, and a
full-text index over it that narrows a search to the pages that can match."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from vethuq._db import _Database, _PageSearch, _SearchDdl
from vethuq._settings import _Settings
from vethuq_addon_api import Normalizer, Pipeline

_logger = logging.getLogger("vethuq.search")


@dataclass(frozen=True)
class _Scope:
    """Which files a search looks in: only these file extensions and/or sources (None: any)."""

    extensions: tuple[str, ...] | None = None  # lower case, with the dot: the file types asked for
    source_ids: tuple[int, ...] | None = None

    def owner_filter(self) -> tuple[str, dict[str, object]]:
        """SQL (to add after `status = 'indexed'` on `document_index`) and its bound values."""
        clause, params = "", {}
        if self.extensions is not None:
            tests = " OR ".join(
                f"lower(file_path) LIKE :e{i} ESCAPE '\\'" for i in range(len(self.extensions))
            )
            clause += f" AND ({tests or '0'})"
            for i, extension in enumerate(self.extensions):
                escaped = extension.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                params[f"e{i}"] = f"%{escaped}"
        if self.source_ids is not None:
            marks = ",".join(f":s{i}" for i in range(len(self.source_ids))) or "NULL"
            clause += f" AND source_id IN ({marks})"
            params.update({f"s{i}": value for i, value in enumerate(self.source_ids)})
        return clause, params


class _SearchIndex:
    SIGNATURE_KEY = "search_index_signature"
    BATCH = 500
    TRIGRAM_MIN_CHARS = 3  # the shortest query the trigram index can serve

    def __init__(self, database: _Database, normalizers: Callable[[], Sequence[Normalizer]]):
        self.database = database
        self._normalizers = normalizers

    # ----- the signature ----------------------------------------------------------------------

    def signature(self) -> str:
        """A short identity of the installed normalizers (names and versions, in order): the index
        is only valid for the set it was built with."""
        parts = [f"{n.id}:{n.version}" for n in self._normalizers()]
        return hashlib.sha256(";".join(parts).encode()).hexdigest()[:16]

    def form(self, text_: str) -> str:
        """`text_` as the index records it."""
        return Pipeline.index_form(self._normalizers(), text_)

    # ----- keeping it up to date --------------------------------------------------------------

    def sync(self) -> tuple[int, bool]:
        """Bring the index up to date: (pages indexed now, whether it was rebuilt because the
        installed normalizers changed). Cheap when nothing changed."""
        rebuilt = False
        signature = self.signature()
        with self.database.session() as session:
            stored = _Settings.get(session, self.SIGNATURE_KEY)
            if stored != signature:
                # A rebuild when there was a different index; the first build is not one.
                rebuilt = stored is not None and session.query(_PageSearch).first() is not None
                session.query(_PageSearch).delete()
                _Settings.set(session, self.SIGNATURE_KEY, signature)
        total = 0
        while True:
            with self.database.session() as session:
                rows = session.execute(
                    text(
                        "SELECT p.id, p.text FROM pdf_pages p "
                        "WHERE p.status = 'done' "
                        "AND NOT EXISTS (SELECT 1 FROM page_search s WHERE s.page_id = p.id) "
                        "ORDER BY p.id LIMIT :n"
                    ),
                    {"n": self.BATCH},
                ).all()
                for page_id, page_text in rows:
                    session.add(
                        _PageSearch(
                            page_id=page_id, norm_text=self.form(page_text.replace("\n", " "))
                        )
                    )
            total += len(rows)
            if len(rows) < self.BATCH:
                break
        if rebuilt:
            _logger.info("Search index rebuilt for the installed normalizers (%d pages)", total)
        return total, rebuilt

    def rebuild(self) -> int:
        """Throw the index away and build it again. Returns the pages indexed."""
        with self.database.session() as session:
            session.query(_PageSearch).delete()
        return self.sync()[0]

    def counts(self) -> tuple[int, int]:
        """(pages in the index, pages that should be in it)."""
        with self.database.session() as session:
            indexed = session.execute(text("SELECT count(*) FROM page_search")).scalar_one()
            wanted = session.execute(
                text("SELECT count(*) FROM pdf_pages WHERE status = 'done'")
            ).scalar_one()
        return indexed, wanted

    def is_current(self) -> bool:
        with self.database.session() as session:
            return _Settings.get(session, self.SIGNATURE_KEY) == self.signature()

    # ----- narrowing a search -----------------------------------------------------------------

    def has_fts(self) -> bool:
        with self.database.session() as session:
            return _SearchDdl.has_fts(session.connection())

    def match_expression(self, query: str) -> str | None:
        """`query` as a quoted FTS5 phrase over the index form, or None when it is too short for
        the trigram index (every page is then a candidate for the plain substring test)."""
        folded = self.form(query.replace("\n", " "))
        if len(folded) < self.TRIGRAM_MIN_CHARS:
            return None
        return '"' + folded.replace('"', '""') + '"'

    def folded_query(self, query: str) -> str:
        return self.form(query.replace("\n", " "))

    def candidate_rows(
        self,
        session: Session,
        query: str | None,
        after: int,
        languages: Sequence[int] | None,
        use_fts: bool,
        scope: _Scope | None = None,
    ) -> list[Row]:
        """The next batch of pages (by id, after `after`) of searchable documents that can hold
        `query`. A page is a candidate when its index form holds the query's."""
        join, where, params = "", ["p.status = 'done'", "p.id > :after"], {"after": after}
        expression = self.match_expression(query) if query else None
        if expression is not None and use_fts:
            join = f"JOIN {_SearchDdl.FTS_TABLE} f ON f.rowid = p.id "
            where.append("f.norm_text MATCH :match")
            params["match"] = expression
        else:
            join = "JOIN page_search s ON s.page_id = p.id "
            if query:
                where.append("instr(s.norm_text, :needle) > 0")
                params["needle"] = self.folded_query(query)
        owners, owner_params = (scope or _Scope()).owner_filter()
        where.append(
            "p.document_id IN (SELECT document_id FROM document_index "  # noqa: S608 - fixed names and bound values
            f"WHERE status = 'indexed' AND document_id IS NOT NULL{owners})"
        )
        params.update(owner_params)
        if languages is not None:
            marks = ",".join(f":l{i}" for i in range(len(languages))) or "NULL"
            where.append(
                "p.document_id IN (SELECT document_id FROM document_languages "  # noqa: S608 - fixed names and bound values
                f"WHERE language_id IN ({marks}))"
            )
            params.update({f"l{i}": language for i, language in enumerate(languages)})
        sql = (
            "SELECT p.id, p.document_id, p.page_number, p.text, p.source FROM pdf_pages p "  # noqa: S608 - fixed names and bound values
            f"{join}WHERE {' AND '.join(where)} ORDER BY p.id LIMIT {self.BATCH}"
        )
        return session.execute(text(sql), params).all()

    def page_count(self, session: Session, document_id: int) -> int:
        return session.execute(
            text("SELECT count(*) FROM pdf_pages WHERE document_id = :d"), {"d": document_id}
        ).scalar_one()
