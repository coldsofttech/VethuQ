"""Which languages a page's text is in, for pages whose text did not come from an OCR language.

A native page (its text read straight from the PDF's text layer) was not read in any language, so
nothing recorded one; every such page then counted as English, and a Telugu one was filed as
English in the statistics and left out of `--lang te` searches. Its language is the one its
characters are written in: the languages whose script the text contains, the one with the most
characters being the page's `language`, and all of them (when more than one) its `ocr_langs`.

Text with no letters of a script other than the default's is left exactly as it was, so English
pages are stored as before.
"""

from __future__ import annotations

from vethuq_core.languages import Scripts
from vethuq_core.ocr.catalog import OcrCatalog
from vethuq_core.readers.storage import PageResult
from vethuq_core.storage import Storage


class PageLanguages:
    @staticmethod
    def of_text(text: str) -> list[str]:
        """The ids of the languages `text` is written in, most characters first (ties: catalog
        order); empty when it has no letters of a known script."""
        counts = Scripts.counts(text)
        found = [
            (counts[lang.script], index, lang.id)
            for index, lang in enumerate(OcrCatalog.languages())
            if lang.script in counts
        ]
        return [lang_id for _count, _index, lang_id in sorted(found, key=lambda f: (-f[0], f[1]))]

    @staticmethod
    def needs_tagging(ids: list[str]) -> bool:
        """Whether the text is in something other than the default language alone."""
        return bool(ids) and ids != [OcrCatalog.default_language().id]

    @staticmethod
    def tag(storage: Storage, document_id: int, file_type: str, pages: list[PageResult]) -> None:
        """Record the language(s) of the native and mixed `pages` just stored for `document_id`
        (an OCR page already has the language it was read in)."""
        wanted: dict[int, tuple[str, str]] = {}
        for number, page in enumerate(pages, start=1):
            if page.source not in ("native", "mixed"):
                continue
            ids = PageLanguages.of_text(page.text)
            if not PageLanguages.needs_tagging(ids):
                continue
            if page.language and page.language not in ids:
                ids.append(page.language)  # a mixed page's image regions were read in this one
            wanted[number] = (ids[0], ",".join(ids) if len(ids) > 1 else "")
        if not wanted:
            return
        table = "pdf_pages" if file_type == "pdf" else "image_pages"
        for row in storage.list_ocr_document_pages(table, document_id):
            if row["page_number"] in wanted:
                language, ocr_langs = wanted[row["page_number"]]
                storage.update_ocr_page_languages(table, row["id"], language, ocr_langs)
