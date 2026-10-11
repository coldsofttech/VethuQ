"""A stand-in host for testing an add-on without VethuQ."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from vethuq_addon_api.api import API_VERSION
from vethuq_addon_api.errors import CreditsExhaustedError
from vethuq_addon_api.ocr import OcrResult
from vethuq_addon_api.readers import DocumentReader, ReadPage
from vethuq_addon_api.scheduling import WorkerScheduler, WorkPlan
from vethuq_addon_api.search import Folded, Normalizer, PageText, SearchCorpus
from vethuq_addon_api.tiers import JobState, OcrExecutor, OcrRequest


class FakeCredits:
    """Implements `Credits` in memory. Tests set `balance` (milli-credits) and `rates`, and read
    `charges` (amount, note)."""

    def __init__(self, balance_milli: int = 0, rates: dict[str, float] | None = None) -> None:
        self.balance = balance_milli
        self.rates = rates or {}
        self.charges: list[tuple[int, str]] = []

    def rate(self, key: str, default: float) -> float:
        return self.rates.get(key, default)

    def balance_milli(self) -> int:
        return self.balance

    def charge(self, amount_milli: int, *, note: str = "") -> None:
        if amount_milli > self.balance:
            raise CreditsExhaustedError("There aren't enough credits.")
        self.balance -= amount_milli
        self.charges.append((amount_milli, note))


class FakeHost:
    """Implements `Host` in memory. Tests can read `settings`, `logs`, `released` and `credits`."""

    def __init__(
        self,
        db_path: Path,
        schema_version: int = 1,
        app_version: str = "0.0.0",
        revoked: frozenset[str] = frozenset(),
        enabled: bool = True,
    ) -> None:
        self._db_path = Path(db_path)
        self._schema_version = schema_version
        self._app_version = app_version
        self._revoked = revoked
        self._enabled = enabled
        self.settings: dict[str, str] = {}
        self.licences: dict[str, str] = {}
        self.logs: list[tuple[int, str]] = []
        self.released = 0
        self.credits = FakeCredits()

    @property
    def api_version(self) -> str:
        return API_VERSION

    @property
    def app_version(self) -> str:
        return self._app_version

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def schema_version(self) -> int:
        return self._schema_version

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        return self.settings.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    def reset_setting(self, key: str) -> None:
        self.settings.pop(key, None)

    def data_dir(self) -> Path:
        folder = self._db_path.parent / "addon-data"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def revoked_licence_ids(self) -> frozenset[str]:
        return self._revoked

    def licence_tokens(self) -> dict[str, str]:
        return dict(self.licences)

    def addon_policy_enabled(self) -> bool:
        return self._enabled

    def release_database(self) -> None:
        self.released += 1

    def log(self, level: int, message: str) -> None:
        self.logs.append((level, message))
        logging.getLogger("vethuq.addon.fake").log(level, message)


class FakeEngine:
    """An `OcrEngine` that returns canned text, for testing code that uses one.

    `texts` maps what `recognize` is given (the image) to the text to return; any other image
    gets `default`. Every call is recorded in `calls`.
    """

    def __init__(
        self,
        texts: dict[str, str] | None = None,
        *,
        default: str = "",
        confidence: float = 0.9,
        language: str = "en",
        name: str = "fake-ocr 1.0",
    ) -> None:
        self._texts = texts or {}
        self._default = default
        self._confidence = confidence
        self._language = language
        self._name = name
        self.calls: list[object] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def language(self) -> str:
        return self._language

    def recognize(self, image: object) -> OcrResult:
        self.calls.append(image)
        text = self._texts.get(image, self._default) if isinstance(image, str) else self._default
        lines = tuple((line, self._confidence) for line in text.splitlines())
        return OcrResult(
            text=text,
            confidence=self._confidence if text else 0.0,
            engine=self._name,
            language=self._language,
            lines=lines,
        )


class FakeReader(DocumentReader):
    """A `DocumentReader` that yields the pages it was given, whatever the file."""

    def __init__(self, pages: list[ReadPage] | None = None) -> None:
        self.pages = pages or []
        self.opened: list[Path] = []

    def read(self, file_path: Path, page_number: int | None = None) -> Iterator[ReadPage]:
        self.opened.append(Path(file_path))
        if page_number is not None:
            yield self.pages[page_number - 1]
            return
        yield from self.pages


class FakeExecutor(OcrExecutor):
    """An `OcrExecutor` for testing code that uses one.

    Synchronous by default: `recognize` returns the text in `texts` for the request's key (else
    `default`). With `asynchronous=True` it behaves like a remote tier: `submit` keeps the batch,
    `poll` answers with `state`, and `collect` returns the results. Every request is in `seen`.
    """

    def __init__(
        self,
        texts: dict[str, str] | None = None,
        *,
        default: str = "",
        confidence: float = 0.9,
        asynchronous: bool = False,
        state: JobState = JobState.DONE,
        where: str = "a test executor",
    ) -> None:
        self.texts = texts or {}
        self.default = default
        self.confidence = confidence
        self.asynchronous = asynchronous
        self.state = state
        self.where = where
        self.seen: list[OcrRequest] = []
        self.jobs: dict[str, list[OcrRequest]] = {}
        self.cancelled: list[str] = []

    def describe(self) -> str:
        return self.where

    def _read(self, request: OcrRequest) -> OcrResult:
        text = self.texts.get(request.key, self.default)
        return OcrResult(
            text=text,
            confidence=self.confidence if text else 0.0,
            engine="fake-executor 1.0",
            language=request.language.id,
            lines=tuple((line, self.confidence) for line in text.splitlines()),
        )

    def recognize(self, request: OcrRequest) -> OcrResult:
        if self.asynchronous:
            return super().recognize(request)
        self.seen.append(request)
        return self._read(request)

    def submit(self, requests: Sequence[OcrRequest]) -> str:
        if not self.asynchronous:
            return super().submit(requests)
        handle = f"job-{len(self.jobs) + 1}"
        self.jobs[handle] = list(requests)
        self.seen.extend(requests)
        return handle

    def poll(self, handle: str) -> JobState:
        if not self.asynchronous:
            return super().poll(handle)
        return self.state

    def collect(self, handle: str) -> dict[str, OcrResult]:
        if not self.asynchronous:
            return super().collect(handle)
        return {r.key: self._read(r) for r in self.jobs[handle]}

    def cancel(self, handle: str) -> None:
        if not self.asynchronous:
            return super().cancel(handle)
        self.cancelled.append(handle)


class FakeNormalizer(Normalizer):
    """A `Normalizer` for testing code that uses one: at any level other than `off` it replaces
    each character in `table` (default: upper case to lower case, one character for one)."""

    levels = ("off", "on")
    identity = "off"

    def __init__(self, id: str = "fake", table: dict[str, str] | None = None, order: int = 100):
        self.id = id
        self.order = order
        self.table = table or {c: c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}

    def fold(self, text: str, level: str) -> Folded:
        if level == self.identity:
            return Folded(text)
        return Folded("".join(self.table.get(char, char) for char in text))

    def index_form(self, text: str) -> str:
        return self.fold(text, "on").text


class FakeCorpus(SearchCorpus):
    """A `SearchCorpus` over pages given as text. Every call to `candidates` is in `queries`."""

    def __init__(self, texts: Iterable[str] = ()) -> None:
        self.pages = [
            PageText(i, 1 + i // 10, 1 + i % 10, 10, text) for i, text in enumerate(texts, start=1)
        ]
        self.queries: list[str | None] = []

    def candidates(self, query: str | None = None) -> Iterator[PageText]:
        self.queries.append(query)
        yield from self.pages


class FakeScheduler(WorkerScheduler):
    """A `WorkerScheduler` answering from a list (the last repeats); the plans it saw are kept."""

    def __init__(self, *answers: int) -> None:
        self.answers = list(answers) or [1]
        self.plans: list[WorkPlan] = []

    def allowed(self, plan: WorkPlan) -> int:
        self.plans.append(plan)
        index = min(len(self.plans), len(self.answers)) - 1
        return self.answers[index]
