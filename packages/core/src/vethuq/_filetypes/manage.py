"""Turning file types on and off, and the ones VethuQ ships with."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from vethuq._errors import _FileTypeUnavailableError
from vethuq._settings import _FileTypeSettings
from vethuq_addon_api import FileTypeSpec


@dataclass(frozen=True)
class _FileTypeView:
    spec: FileTypeSpec
    enabled: bool

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def usable(self) -> bool:
        return self.spec.available and self.enabled


class _FileTypes:
    # Installed with VethuQ itself: the PDF, text, CSV and Markdown add-ons.
    DEFAULT_IDS = ("csv", "markdown", "pdf", "txt")

    @staticmethod
    def views(session: Session, specs: list[FileTypeSpec]) -> list[_FileTypeView]:
        disabled = set(_FileTypeSettings.get_disabled(session))
        return [_FileTypeView(spec, spec.id not in disabled) for spec in specs]

    @staticmethod
    def find(session: Session, specs: list[FileTypeSpec], code: str) -> _FileTypeView:
        """One file type by id. Raises if no installed add-on provides it."""
        wanted = str(code).strip().lower()
        views = _FileTypes.views(session, specs)
        found = next((v for v in views if v.id == wanted), None)
        if found is None:
            raise _FileTypeUnavailableError(
                f"Unknown file type '{wanted}'.",
                f"Installed file types: {', '.join(v.id for v in views) or 'none'}.",
            )
        return found

    @staticmethod
    def enable(session: Session, specs: list[FileTypeSpec], code: str) -> _FileTypeView:
        """Switch a file type back on. It must be available."""
        view = _FileTypes.find(session, specs, code)
        if not view.spec.available:
            why = view.spec.reason or "it isn't available"
            raise _FileTypeUnavailableError(
                f"The {view.spec.label} file type can't be used: {why}.",
                "Install or renew its add-on, then try again.",
            )
        disabled = _FileTypeSettings.get_disabled(session)
        if view.id in disabled:
            _FileTypeSettings.set_disabled(session, [i for i in disabled if i != view.id])
        return _FileTypes.find(session, specs, view.id)

    @staticmethod
    def disable(session: Session, specs: list[FileTypeSpec], code: str) -> _FileTypeView:
        """Switch a file type off, so its files are no longer read."""
        view = _FileTypes.find(session, specs, code)
        disabled = _FileTypeSettings.get_disabled(session)
        if view.id not in disabled:
            _FileTypeSettings.set_disabled(session, [*disabled, view.id])
        return _FileTypes.find(session, specs, view.id)
