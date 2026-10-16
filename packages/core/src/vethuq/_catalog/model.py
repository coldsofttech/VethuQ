"""The parsed catalog: the add-ons and bundles that exist, with their descriptions.

Unknown fields are ignored. An entry that lacks a required field is skipped, not fatal: the rest of
a signed catalog stands. All text is plain text.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from vethuq._policy.errors import _PolicyFormatError
from vethuq._policy.model import Policy
from vethuq.enums import PolicySource, PolicyStatus

_TEXT_FIELDS = ("label", "summary", "description")


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _words(entry: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = entry.get(key)
    items = value if isinstance(value, list) else []
    return tuple(dict.fromkeys(item for item in items if isinstance(item, str) and item))


def _translations(entry: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    raw = entry.get("translations")
    for language, texts in raw.items() if isinstance(raw, dict) else []:
        if isinstance(language, str) and isinstance(texts, dict):
            kept = {k: v for k, v in texts.items() if k in _TEXT_FIELDS and _text(v)}
            if kept:
                found[language] = kept
    return found


def _localize(item: Any, language: str | None) -> Any:
    """`item` with its text in `language` (`es`, or `es-MX` falling back to `es`), else as it is."""
    if not language:
        return item
    wanted = language.lower().replace("_", "-")
    for candidate in (wanted, wanted.split("-")[0]):
        for key, texts in item.translations.items():
            if key.lower() == candidate:
                return replace(item, **texts)
    return item


@dataclass(frozen=True)
class CatalogAddon:
    """An add-on that exists, whether or not it is installed here."""

    id: str
    label: str
    summary: str
    description: str = ""
    kind: str = ""  # file-type, language, search-engine, ocr, tier, backup, ... (shown as it is)
    licence: str = ""  # "free" or "licensed"; "" when the catalog doesn't say
    bundles: tuple[str, ...] = ()
    status: str = (
        "available"  # available, coming_soon, deprecated (anything else counts as available)
    )
    min_client: str | None = None
    size_bytes: int | None = None
    docs_url: str | None = None
    request_url: str | None = None
    translations: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    def localized(self, language: str | None) -> CatalogAddon:
        return _localize(self, language)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "summary": self.summary,
            "description": self.description,
            "kind": self.kind,
            "licence": self.licence,
            "bundles": list(self.bundles),
            "status": self.status,
            "min_client": self.min_client,
            "size_bytes": self.size_bytes,
            "docs_url": self.docs_url,
            "request_url": self.request_url,
        }


@dataclass(frozen=True)
class CatalogBundle:
    """Add-ons that are licensed together."""

    id: str
    label: str
    summary: str
    addons: tuple[str, ...]
    description: str = ""
    status: str = "available"
    docs_url: str | None = None
    request_url: str | None = None
    translations: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    def localized(self, language: str | None) -> CatalogBundle:
        return _localize(self, language)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "summary": self.summary,
            "description": self.description,
            "addons": list(self.addons),
            "status": self.status,
            "docs_url": self.docs_url,
            "request_url": self.request_url,
        }


@dataclass(frozen=True)
class Catalog:
    schema_version: int
    sequence: int
    issued_at: datetime
    kid: str
    addons: tuple[CatalogAddon, ...] = ()
    bundles: tuple[CatalogBundle, ...] = ()
    request_url: str | None = None  # where to ask, when an entry has no address of its own
    raw: Mapping[str, Any] = field(default_factory=dict)

    def addon(self, addon_id: str) -> CatalogAddon | None:
        return next((a for a in self.addons if a.id == addon_id), None)

    def bundle(self, bundle_id: str) -> CatalogBundle | None:
        return next((b for b in self.bundles if b.id == bundle_id), None)

    def to_dict(self) -> dict[str, Any]:
        """The verified payload exactly as signed, including fields this client doesn't use."""
        return dict(self.raw)

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @staticmethod
    def from_payload(payload: Mapping[str, Any]) -> Catalog:
        """Build a catalog from an already verified payload. Raises `_PolicyFormatError`."""
        schema, sequence, kid = (payload.get(k) for k in ("schema_version", "sequence", "kid"))
        if not isinstance(schema, int) or isinstance(schema, bool):
            raise _PolicyFormatError("schema_version must be an integer")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise _PolicyFormatError("sequence must be an integer of at least 1")
        if not isinstance(kid, str) or not kid:
            raise _PolicyFormatError("kid must be a non-empty string")
        if not isinstance(payload.get("addons"), list) or not isinstance(
            payload.get("bundles"), list
        ):
            raise _PolicyFormatError("addons and bundles must be lists")
        return Catalog(
            schema_version=schema,
            sequence=sequence,
            issued_at=Policy.parse_time(payload.get("issued_at")),
            kid=kid,
            addons=Catalog._addons(payload["addons"]),
            bundles=Catalog._bundles(payload["bundles"]),
            request_url=Catalog._url(payload.get("request_url")),
            raw=dict(payload),
        )

    @staticmethod
    def _url(value: Any) -> str | None:
        """Only an https address is kept: a catalog never sends a person to anything else."""
        return value if isinstance(value, str) and value.startswith("https://") else None

    @staticmethod
    def _addons(items: list[Any]) -> tuple[CatalogAddon, ...]:
        found: dict[str, CatalogAddon] = {}
        for entry in items:
            if not isinstance(entry, dict):
                continue
            ident, label, summary = (_text(entry.get(k)) for k in ("id", "label", "summary"))
            if not (ident and label and summary) or ident in found:
                continue
            size = entry.get("size_bytes")
            found[ident] = CatalogAddon(
                id=ident,
                label=label,
                summary=summary,
                description=_text(entry.get("description")) or "",
                kind=_text(entry.get("kind")) or "",
                licence=_text(entry.get("licence")) or "",
                bundles=_words(entry, "bundles"),
                status=_text(entry.get("status")) or "available",
                min_client=_text(entry.get("min_client")),
                size_bytes=size if isinstance(size, int) and not isinstance(size, bool) else None,
                docs_url=Catalog._url(entry.get("docs_url")),
                request_url=Catalog._url(entry.get("request_url")),
                translations=_translations(entry),
            )
        return tuple(found.values())

    @staticmethod
    def _bundles(items: list[Any]) -> tuple[CatalogBundle, ...]:
        found: dict[str, CatalogBundle] = {}
        for entry in items:
            if not isinstance(entry, dict):
                continue
            ident, label, summary = (_text(entry.get(k)) for k in ("id", "label", "summary"))
            members = _words(entry, "addons")
            if not (ident and label and summary and members) or ident in found:
                continue
            found[ident] = CatalogBundle(
                id=ident,
                label=label,
                summary=summary,
                addons=members,
                description=_text(entry.get("description")) or "",
                status=_text(entry.get("status")) or "available",
                docs_url=Catalog._url(entry.get("docs_url")),
                request_url=Catalog._url(entry.get("request_url")),
                translations=_translations(entry),
            )
        return tuple(found.values())


@dataclass(frozen=True)
class CatalogResult:
    """What a catalog call returned: the catalog to use, where it came from, and what happened."""

    catalog: Catalog
    source: PolicySource
    status: PolicyStatus
    detail: str = ""  # why a fetch failed or was refused, or why none was made
    update_required: bool = False  # the latest catalog needs a newer VethuQ than this one

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "status": self.status.value,
            "detail": self.detail,
            "update_required": self.update_required,
            "sequence": self.catalog.sequence,
            "kid": self.catalog.kid,
            "addons": len(self.catalog.addons),
            "bundles": len(self.catalog.bundles),
        }

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)
