"""Internal language service; the public view is `vethuq.languages`."""

from __future__ import annotations

from vethuq._languages.languages import _LanguageCatalog, _Languages, _LanguageView

__all__ = ["_LanguageCatalog", "_LanguageView", "_Languages"]
