"""Installing licences, and asking for them.

    client.licences.install(token)                    # one key for every add-on it lists
    client.licences.install_file("acme.vqlic")
    client.licences.show()                            # what is installed, by licence
    client.licences.request_code()                    # what to send the admin
    client.licences.request(kind="new", addons=["docx"]).url   # a prefilled public issue

A licence is only ever *stored* here, as the `licence` setting of each add-on it lists; every
add-on still checks its own licence. Needs `vethuq-entitlements` (which holds the keys).

**A request is public.** The prefilled issue is opened in VethuQ's public repository, so the
request holds only the request code (the anonymous device hash, the numeric GitHub id if you asked
for one, the runner owner id, the app version), the add-ons or wallet wanted and a short note.
Never file names, paths, content, licence keys, tokens, e-mail addresses or other contact details.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from vethuq._addons import _AddonSettingsStore
from vethuq._addons.host import _Host
from vethuq._errors import _InvalidLicenceError, _LicenceRequestError
from vethuq._version import _Version

if TYPE_CHECKING:
    from vethuq.addons.manage import Addons

__all__ = [
    "BundleLicence",
    "InstalledLicence",
    "LicenceInstall",
    "LicenceRequest",
    "Licences",
    "REQUEST_FIELDS",
    "REQUEST_PRIVACY",
]

REPOSITORY = "coldsofttech/VethuQ"
LICENCE_KEY = "licence"
GITHUB_ID_KEY = "github_owner_id"
TOKEN_ENV = ("VETHUQ_GITHUB_TOKEN", "GITHUB_TOKEN")
MAX_TOKEN_BYTES = 16 * 1024
# The only fields a prefilled request may carry (the issue forms in `.github/ISSUE_TEMPLATE` have
# exactly these ids): nothing else can reach the URL.
REQUEST_FIELDS = ("request_code", "addons", "wallet", "note")
REQUEST_PRIVACY = (
    "This opens a PUBLIC issue in VethuQ's repository on GitHub, so anyone can read it.\n"
    "It will contain only:\n"
    "  - your request code: an anonymous hash of this device, your numeric GitHub id (only if you "
    "asked for one), the runner owner's numeric id, and the VethuQ version;\n"
    "  - the add-ons, bundle or wallet you ask for, and an optional short note.\n"
    "It never contains file names, paths, document content, licence keys, tokens, e-mail "
    "addresses or other contact details, and you should not add any to the note.\n"
    "Your licence key is not sent in the issue: the admin sends it to you privately."
)
_FORMS = {
    "new": ("licence-request.yml", "Licence request"),
    "top-up": ("topup-request.yml", "Top-up request"),
    "rebind": ("rebind-request.yml", "Re-bind request"),
}
_ID = re.compile(r"[a-z][a-z0-9-]{0,39}")
_WALLET = re.compile(r"[a-z0-9][a-z0-9:_.-]{0,39}")


@dataclass(frozen=True)
class LicenceInstall:
    """What installing a licence did for one add-on it lists."""

    addon_id: str
    status: str  # stored, replaced, unchanged, not_installed
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"addon_id": self.addon_id, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class InstalledLicence:
    """One installed licence token and the add-ons holding it."""

    licence_id: str | None
    kind: str | None
    status: str  # `ok`, or why it isn't (expired, revoked, device_mismatch, ...)
    detail: str
    valid_until: str | None
    lists: tuple[str, ...]  # the add-ons the licence unlocks, directly or through its bundles
    installed_on: tuple[str, ...]  # the add-ons that hold this token
    bundles: tuple[str, ...] = ()  # the bundles the licence lists

    def to_dict(self) -> dict[str, Any]:
        return {
            "licence_id": self.licence_id,
            "kind": self.kind,
            "status": self.status,
            "detail": self.detail,
            "valid_until": self.valid_until,
            "lists": list(self.lists),
            "installed_on": list(self.installed_on),
            "bundles": list(self.bundles),
        }


@dataclass(frozen=True)
class BundleLicence:
    """Where one bundle stands on licences: `free` (nothing in it needs one), `licensed` (an
    installed licence covers it), `expired` (the licence for it has ended or isn't valid) or
    `not_licensed`."""

    bundle_id: str
    state: str
    licence_id: str | None = None
    valid_until: str | None = None
    licensed_addons: tuple[str, ...] = ()  # the add-ons of the bundle that need a licence

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "state": self.state,
            "licence_id": self.licence_id,
            "valid_until": self.valid_until,
            "licensed_addons": list(self.licensed_addons),
        }


@dataclass(frozen=True)
class LicenceRequest:
    """A licence request, ready to open: the request code, the public issue form's URL, exactly
    the fields it carries and the privacy statement to show before opening it."""

    kind: str
    code: str
    url: str
    fields: dict[str, str] = field(default_factory=dict)
    privacy: str = REQUEST_PRIVACY

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "code": self.code,
            "url": self.url,
            "fields": dict(self.fields),
            "privacy": self.privacy,
        }


class Licences:
    """Licences: install one for every add-on it lists, see what is installed, and ask for one.

    Not created directly: use `VethuQ().licences`.
    """

    def __init__(
        self,
        addons: Addons,
        db_path: Path,
        open_database: Callable[[], None],
        urlopen: Callable[..., Any] | None = None,
    ) -> None:
        self._addons = addons
        self._db_path = Path(db_path)
        self._open_database = open_database
        self._urlopen = urlopen or urllib.request.urlopen

    # ----- the keys ---------------------------------------------------------------------------

    @staticmethod
    def _entitlements() -> Any:
        try:
            import vethuq_entitlements  # noqa: PLC0415 - optional, and it holds the keys
        except ImportError:
            raise _InvalidLicenceError(
                "Licences can't be checked here.", "Install vethuq-entitlements."
            ) from None
        return vethuq_entitlements

    def _revoked(self) -> frozenset[str]:
        host = _Host("vethuq", self._db_path, lambda: None)
        try:
            return host.revoked_licence_ids()
        except Exception:  # noqa: BLE001 - a policy problem never blocks reading a licence
            return frozenset()

    def _verify(self, token: str, github_owner_id: int | None = None) -> Any:
        module = self._entitlements()
        owner = github_owner_id if github_owner_id is not None else self.saved_github_id()
        return module.Licences().verify(token, revoked=self._revoked(), github_owner_id=owner)

    # ----- installing -------------------------------------------------------------------------

    @staticmethod
    def read_token(text: str) -> str:
        """The token in pasted text or in a `.vqlic` file's text (surrounding space and a byte order
        mark are ignored; a file holds one token)."""
        token = "".join(text.lstrip("﻿").split())
        if not token or len(token.encode()) > MAX_TOKEN_BYTES:
            raise _InvalidLicenceError(
                "That isn't a licence.", "Paste the whole key, or choose the .vqlic file."
            )
        return token

    def install(self, token: str, github_owner_id: int | None = None) -> list[LicenceInstall]:
        """Verify `token` and store it as the licence of every installed add-on it lists, so one
        paste unlocks them all. Each add-on still checks the token itself.

        Raises `InvalidLicenceError` (storing nothing) for a licence that isn't valid, is revoked
        or expired, is for another device, or lists no add-on. An add-on the licence lists that is
        not installed is reported as `not_installed`, not an error. `github_owner_id` is checked
        against a licence bound to GitHub accounts (see `request_code`)."""
        token = self.read_token(token)
        licence = self._verify(token, github_owner_id)
        if not licence.ok:
            raise _InvalidLicenceError(
                f"The licence isn't valid: {licence.detail or licence.status.value}.",
                "Check that you pasted the whole key, and that it was issued for this device.",
            )
        moment = datetime.now(UTC)
        members = self._bundle_members()
        reached: dict[str, str] = {e.addon_id: "" for e in licence.entitlements}
        unknown: list[LicenceInstall] = []
        for bundle in getattr(licence, "bundles", ()):  # an older entitlements has none
            if not bundle.is_active(moment):
                unknown.append(
                    LicenceInstall(
                        bundle.bundle_id, "expired", "the licence for this bundle has ended"
                    )
                )
            elif bundle.bundle_id not in members:
                unknown.append(
                    LicenceInstall(
                        bundle.bundle_id,
                        "unknown_bundle",
                        "this VethuQ doesn't know the bundle: refresh the catalog or update VethuQ",
                    )
                )
            else:
                for addon_id in members[bundle.bundle_id]:
                    reached.setdefault(addon_id, f"through the {bundle.bundle_id} bundle")
        if not reached:
            if unknown:
                raise _InvalidLicenceError(
                    "No add-on can be unlocked with this licence.",
                    "; ".join(f"{u.addon_id}: {u.detail}" for u in unknown) + ".",
                )
            raise _InvalidLicenceError(
                "This licence doesn't unlock any add-on.",
                "If it carries credits, redeem it with `client.credits.redeem_licence(token)`.",
            )
        results = list(unknown)
        for addon_id, via in sorted(reached.items()):
            if not self._addons.is_installed(addon_id):
                results.append(
                    LicenceInstall(addon_id, "not_installed", "the add-on isn't installed")
                )
                continue
            settings = self._addons.settings(addon_id)
            current = settings.get(LICENCE_KEY)
            if current == token:
                results.append(LicenceInstall(addon_id, "unchanged", via))
                continue
            settings.set(LICENCE_KEY, token)
            results.append(LicenceInstall(addon_id, "replaced" if current else "stored", via))
        return results

    def _bundle_members(self) -> dict[str, tuple[str, ...]]:
        """`{bundle id: add-on ids}`: what the running add-ons say they are in (`licence_bundles`),
        and the catalog's bundles (the signed one, or the baseline). Makes no request."""
        members: dict[str, set[str]] = {}
        with contextlib.suppress(Exception):  # a broken add-on never blocks reading a licence
            for addon_id, bundles in self._addons.licence_bundles().items():
                for bundle in bundles:
                    members.setdefault(bundle, set()).add(addon_id)
        with contextlib.suppress(Exception):  # without a catalog only the add-ons' own word is used
            for entry in self._addons._catalog_client().bundles():  # noqa: SLF001
                members.setdefault(entry.id, set()).update(entry.addons)
        return {bundle: tuple(sorted(ids)) for bundle, ids in members.items()}

    def install_file(
        self, path: str | Path, github_owner_id: int | None = None
    ) -> list[LicenceInstall]:
        """`install` for a `.vqlic` file."""
        file = Path(path)
        try:
            if file.stat().st_size > MAX_TOKEN_BYTES:
                raise _InvalidLicenceError(f"{file.name} is too large to be a licence.")
            text = file.read_text(encoding="utf-8")
        except OSError as error:
            raise _InvalidLicenceError(
                f"The licence file can't be read ({error.strerror or error}).",
                "Check the path.",
            ) from None
        except UnicodeDecodeError:
            raise _InvalidLicenceError(f"{file.name} isn't a licence file.") from None
        return self.install(text, github_owner_id)

    def show(self) -> list[InstalledLicence]:
        """The installed licences, one per distinct token, with the add-ons each lists and where
        it is installed (every check is made now)."""
        by_token: dict[str, list[str]] = {}
        for addon_id, token in sorted(_AddonSettingsStore.licences(self._db_path).items()):
            by_token.setdefault(token, []).append(addon_id)
        shown = []
        for token, holders in by_token.items():
            licence = self._verify(token)
            until = (
                licence.valid_until.astimezone(UTC).strftime("%Y-%m-%d")
                if licence.valid_until
                else None
            )
            members = self._bundle_members()
            covered = {e.addon_id for e in licence.entitlements}
            for bundle in getattr(licence, "bundles", ()):
                covered.update(members.get(bundle.bundle_id, ()))
            shown.append(
                InstalledLicence(
                    licence.licence_id,
                    licence.kind,
                    licence.status.value,
                    licence.detail,
                    until,
                    tuple(sorted(covered)),
                    tuple(holders),
                    tuple(sorted(b.bundle_id for b in getattr(licence, "bundles", ()))),
                )
            )
        return sorted(shown, key=lambda i: (i.licence_id or "", i.installed_on))

    def bundles(self) -> list[BundleLicence]:
        """Every bundle known here (the catalog's, and the ones add-ons say they are in) and where
        it stands on licences: `free` when none of its add-ons needs one, `licensed` when an
        installed, valid licence covers all the add-ons that do, `expired` when a licence that
        would cover them isn't valid (any more), else `not_licensed`. Makes no request."""
        try:
            needs = {e.id for e in self._addons.catalog() if e.licence == "licensed"}
        except Exception:  # noqa: BLE001 - without a catalog only the add-ons' own word is used
            needs = set()
        declared = self._addons.licence_bundles()
        needs.update(declared)  # an add-on that names bundles has a licence
        held = self.show()
        found = []
        for bundle, members in sorted(self._bundle_members().items()):
            required = tuple(sorted(a for a in members if a in needs))
            if not required:
                found.append(BundleLicence(bundle, "free"))
                continue
            covering = [h for h in held if set(required) <= set(h.lists)]
            valid = next((h for h in covering if h.status == "ok"), None)
            if valid is not None:
                found.append(
                    BundleLicence(bundle, "licensed", valid.licence_id, valid.valid_until, required)
                )
            elif covering:
                first = covering[0]
                found.append(
                    BundleLicence(bundle, "expired", first.licence_id, first.valid_until, required)
                )
            else:
                found.append(BundleLicence(bundle, "not_licensed", licensed_addons=required))
        return found

    # ----- asking -----------------------------------------------------------------------------

    @staticmethod
    def device_hash() -> str:
        """The anonymous hash of this device that a device-bound licence is issued for."""
        return Licences._entitlements().Licences.device_hash()

    def saved_github_id(self) -> int | None:
        """The numeric GitHub id saved by an earlier request that asked for it, if any."""
        value = _AddonSettingsStore(self._db_path, "vethuq").get(GITHUB_ID_KEY)
        return int(value) if value and value.isdigit() else None

    def github_id(self, login: str | None = None, token: str | None = None) -> int:
        """The numeric GitHub id of `login` (the token's own user when None), asked from GitHub's
        API with `token` (or `VETHUQ_GITHUB_TOKEN` / `GITHUB_TOKEN`). The only call that uses the
        network, made only when you ask for it."""
        token = token or next((os.environ[n] for n in TOKEN_ENV if os.environ.get(n)), None)
        if login is None and not token:
            raise _LicenceRequestError(
                "A GitHub token is needed to look up your GitHub id.",
                "Set VETHUQ_GITHUB_TOKEN, or give the numeric id yourself.",
            )
        if login is not None and not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", login):
            raise _LicenceRequestError(f"{login!r} isn't a GitHub user or organization name.")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "vethuq"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"https://api.github.com/{'users/' + login if login else 'user'}"
        try:
            request = urllib.request.Request(url, headers=headers)  # noqa: S310 - fixed https URL
            with self._urlopen(request, timeout=15) as reply:  # noqa: S310
                found = json.loads(reply.read().decode("utf-8")).get("id")
        except urllib.error.HTTPError as error:
            raise _LicenceRequestError(
                f"GitHub refused the lookup ({error.code}).", "Check the token, or give the id."
            ) from None
        except (OSError, ValueError):
            raise _LicenceRequestError(
                "GitHub can't be reached.", "Check your connection, or give the id yourself."
            ) from None
        if not isinstance(found, int) or found < 1:
            raise _LicenceRequestError("GitHub gave no id for that account.")
        return found

    def request_code(
        self,
        github: bool = False,
        github_owner_id: int | None = None,
        runner_owner: str | None = None,
        runner_owner_id: int | None = None,
        token: str | None = None,
    ) -> str:
        """The request code to send the admin. Contains only the device hash, the app version and,
        when asked for, the numeric GitHub id (`github=True` looks it up, or pass
        `github_owner_id`) and the runner owner's id (`runner_owner` looks it up, or pass
        `runner_owner_id`). Looking an id up is the only use of the network, and the GitHub id is
        remembered so installing a GitHub-bound licence checks it."""
        module = self._entitlements()
        if github and github_owner_id is None:
            github_owner_id = self.github_id(token=token)
        if runner_owner and runner_owner_id is None:
            runner_owner_id = self.github_id(runner_owner, token)
        if github_owner_id is not None:
            self._open_database()
            _AddonSettingsStore(self._db_path, "vethuq").set(GITHUB_ID_KEY, str(github_owner_id))
        try:
            return module.RequestCode.encode(
                module.Licences.device_hash(),
                _Version.app_version(),
                github_owner_id,
                runner_owner_id,
            )
        except ValueError as error:
            raise _LicenceRequestError(f"The request can't be made: {error}.") from None

    @staticmethod
    def _clean(value: str | None, limit: int) -> str:
        text = "".join(ch for ch in (value or "") if ch.isprintable() or ch in " ")
        return " ".join(text.split())[:limit]

    def request(
        self,
        kind: str = "new",
        addons: Sequence[str] = (),
        bundle: str | None = None,
        wallet: str | None = None,
        note: str | None = None,
        code: str | None = None,
        **code_options: Any,
    ) -> LicenceRequest:
        """A request for a licence (`new`), a top-up or a re-bind, as a prefilled issue form of the
        public VethuQ repository. `code` is a request code made earlier; otherwise one is made
        (`code_options` go to `request_code`). Opens nothing: show `privacy` and `fields`, then
        open `url`. Works without GitHub; nothing is sent from here."""
        if kind not in _FORMS:
            raise _LicenceRequestError(
                f"{kind!r} isn't a kind of request.", f"Use one of: {', '.join(_FORMS)}."
            )
        wanted = [*addons, *([bundle] if bundle else [])]
        for item in wanted:
            if not _ID.fullmatch(item):
                raise _LicenceRequestError(
                    f"{item!r} isn't an add-on or bundle id.", "Use ids such as docx or office."
                )
        if wallet is not None and not _WALLET.fullmatch(wallet):
            raise _LicenceRequestError(f"{wallet!r} isn't a wallet name.", "For example: local.")
        fields = {"request_code": code or self.request_code(**code_options)}
        if wanted:
            fields["addons"] = ", ".join(dict.fromkeys(wanted))
        if wallet:
            fields["wallet"] = wallet
        if self._clean(note, 200):
            fields["note"] = self._clean(note, 200)
        template, title = _FORMS[kind]
        query = urlencode({"template": template, "title": title, **fields})
        return LicenceRequest(
            kind,
            fields["request_code"],
            f"https://github.com/{REPOSITORY}/issues/new?{query}",
            fields,
        )
