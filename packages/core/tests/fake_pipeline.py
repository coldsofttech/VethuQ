"""Stand-ins for the PDF, Paddle and quick OCR add-ons, so the indexing pipeline can be tested
without PDFium or PaddleOCR.

A "PDF" here is a JSON file:

    {"pages": [{"text": "native text", "regions": 1, "ocr": "text OCR finds on a scanned page",
                "region_ocr": ["text OCR finds in the image"]}],
     "error": null}

`error` can be "password", "corrupt", "removed" or "boom" (any other failure); `"flaky": n` makes
the first n reads of the file fail.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from vethuq_addon_api import (
    Addon,
    CorruptedFileError,
    DocumentReader,
    FileRemovedError,
    FileTypeSpec,
    LanguageSpec,
    Manifest,
    OcrEngineProvider,
    OcrModelSpec,
    OcrPhaseSpec,
    OcrResult,
    PasswordProtectedError,
    ReadPage,
)


@dataclass
class State:
    reads: list[str] = field(default_factory=list)
    ocr_calls: list[object] = field(default_factory=list)
    engines_created: list[str] = field(default_factory=list)
    flaky: dict[str, int] = field(default_factory=dict)
    downloads: list[str] = field(default_factory=list)
    download_fails: set[str] = field(default_factory=set)
    pdf_available: bool = True
    engine_available: bool = True
    phase_available: bool = True


STATE = State()


def reset() -> None:
    STATE.__dict__.update(State().__dict__)


def pdf_document(*pages: dict, **extra: object) -> str:
    return json.dumps({"pages": list(pages), **extra})


def native_page(text: str = "This page has plenty of native text on it.") -> dict:
    return {"text": text}


def scanned_page(ocr: str = "scanned words found by ocr") -> dict:
    return {"text": "", "ocr": ocr}


def mixed_page(text: str = "Native text with enough words in it.", *images: str) -> dict:
    return {"text": text, "regions": len(images), "region_ocr": list(images)}


class FakeReader(DocumentReader):
    def read(self, file_path: Path, page_number: int | None = None) -> Iterator[ReadPage]:
        STATE.reads.append(str(file_path))
        try:
            document = json.loads(Path(file_path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileRemovedError(file_path) from None
        except ValueError:
            raise CorruptedFileError(file_path, "not valid") from None
        error = document.get("error")
        if error == "password":
            raise PasswordProtectedError(file_path)
        if error == "corrupt":
            raise CorruptedFileError(file_path)
        if error == "removed":
            raise FileRemovedError(file_path)
        if error == "boom":
            raise RuntimeError("boom")
        remaining = STATE.flaky.get(str(file_path), document.get("flaky", 0))
        if remaining > 0:
            STATE.flaky[str(file_path)] = remaining - 1
            raise RuntimeError("flaky failure")
        for number, page in enumerate(document["pages"], start=1):
            if page_number is not None and number != page_number:
                continue
            regions = tuple((float(i), 0.0, 10.0, 10.0) for i in range(page.get("regions", 0)))
            yield ReadPage(
                native_text=page.get("text", ""),
                image_regions=regions,
                render=lambda region, page=page: self_render(page, region),
            )


def self_render(page: dict, region: tuple | None) -> tuple[str, str]:
    if region is None:
        return ("page", page.get("ocr", ""))
    texts = page.get("region_ocr", [])
    index = int(region[0])
    return ("region", texts[index] if index < len(texts) else "")


class FakeEngine:
    def __init__(self, language: str) -> None:
        self._language = language

    @property
    def name(self) -> str:
        return "fake-ocr 1.0"

    @property
    def language(self) -> str:
        return self._language

    def recognize(self, image: object) -> OcrResult:
        STATE.ocr_calls.append((self._language, image))
        text = image[1] if isinstance(image, tuple) else ""
        lines = tuple((line, 0.8) for line in text.splitlines())
        return OcrResult(
            text=text,
            confidence=0.8 if text else 0.0,
            engine=self.name,
            language=self._language,
            image_width=100,
            image_height=200,
            lines=lines,
        )


class FakeProvider(OcrEngineProvider):
    id = "paddle"
    label = "Fake OCR"
    profiles = ("mobile",)

    @property
    def available(self) -> bool:
        return STATE.engine_available

    @property
    def reason(self) -> str:
        return "" if STATE.engine_available else "the fake engine is off"

    def create(self, language: LanguageSpec, profile: str, models_dir: Path, use_gpu: bool = False):
        STATE.engines_created.append(language.id)
        return FakeEngine(language.id)

    def required_models(self, language: LanguageSpec, profile: str) -> Sequence[OcrModelSpec]:
        return [
            OcrModelSpec("det-mobile", "detection", shared=True),
            OcrModelSpec(f"rec-{language.id}", "recognition"),
        ]

    def known_models(self, languages: Sequence[LanguageSpec]) -> Sequence[OcrModelSpec]:
        known: dict[str, OcrModelSpec] = {}
        for language in languages:
            for spec in self.required_models(language, "mobile"):
                known.setdefault(spec.name, spec)
        return list(known.values())

    def model_path(self, models_dir: Path, name: str) -> Path:
        return models_dir / "fake" / name

    def download(self, models_dir: Path, names: Sequence[str], on_progress=None) -> dict[str, str]:
        failed: dict[str, str] = {}
        for name in names:
            STATE.downloads.append(name)
            if name in STATE.download_fails:
                failed[name] = "no network"
                if on_progress:
                    on_progress(name, "failed")
                continue
            path = self.model_path(models_dir, name)
            path.mkdir(parents=True, exist_ok=True)
            (path / "model.bin").write_bytes(b"x" * 10)
            if on_progress:
                on_progress(name, "ready")
        return failed


class FakePdfAddon(Addon):
    manifest = Manifest(id="pdf", name="vethuq-addon-pdf", version="0.1.0")

    def file_types(self):
        return [
            FileTypeSpec(
                "pdf",
                "PDF",
                (".pdf",),
                FakeReader(),
                available=STATE.pdf_available,
                reason="" if STATE.pdf_available else "the PDF reader is off",
            )
        ]


class FakePaddleAddon(Addon):
    manifest = Manifest(id="paddle", name="vethuq-addon-paddle", version="0.1.0")

    def ocr_engines(self):
        return [FakeProvider()]


class FakeOcrQuickAddon(Addon):
    manifest = Manifest(id="ocr-quick", name="vethuq-addon-ocr-quick", version="0.1.0")

    def ocr_phases(self):
        return [
            OcrPhaseSpec(
                "quick",
                "Quick",
                1,
                (0,),
                "mobile",
                available=STATE.phase_available,
                reason="" if STATE.phase_available else "the phase is off",
            )
        ]


ADDONS = {
    "pdf": ("vethuq_addon_pdf", "FakePdfAddon"),
    "paddle": ("vethuq_addon_paddle", "FakePaddleAddon"),
    "ocr-quick": ("vethuq_addon_ocr_quick", "FakeOcrQuickAddon"),
}


def install(folder: Path) -> None:
    """Make the three add-ons look installed (dist-info with entry points) from `folder`."""
    for addon_id, (module, cls) in ADDONS.items():
        dist = folder / f"{module}-0.1.0.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {module}\nVersion: 0.1.0\n", encoding="utf-8"
        )
        (dist / "entry_points.txt").write_text(
            f"[vethuq.addons]\n{addon_id} = tests.fake_pipeline:{cls}\n", encoding="utf-8"
        )
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
