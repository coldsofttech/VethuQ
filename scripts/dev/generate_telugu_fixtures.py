"""Generate the Telugu PDF fixtures in `tests/integration/fixtures/te/pdf` (deterministic).

    uv run python scripts/dev/generate_telugu_fixtures.py

Native PDFs are typeset from HTML by headless Chromium, with the bundled Noto Sans Telugu, so
their text layer holds real, correctly shaped Telugu. Scanned PDFs are rendered from the same kind
of page, degraded (tint, blur, noise, rotation, skew, a stamp ...) and saved as images only, so they
have no text layer and must be read by OCR. The two unreadable ones (password protected, corrupted)
are made from a native file. Everything is original text; the font is licensed under the SIL OFL.

Needs Chromium: set CHROMIUM to its path, or have Playwright's (PLAYWRIGHT_BROWSERS_PATH) around.
After changing a fixture, regenerate `expected.json` with
`scripts/dev/generate_integration_expected.py --lang te --dir <this folder>`.
"""

from __future__ import annotations

import glob
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "packages/vethuq-core/tests/integration/fixtures/te/pdf"
FONT = REPO / "packages/vethuq-ui/src/vethuq_ui/assets/fonts/NotoSansTelugu-Regular.ttf"
FONT_BOLD = REPO / "packages/vethuq-ui/src/vethuq_ui/assets/fonts/NotoSansTelugu-Bold.ttf"
PASSWORD = "Abc123"

CSS = f"""
@font-face {{ font-family: NT; font-weight: 400; src: url("file://{FONT}"); }}
@font-face {{ font-family: NT; font-weight: 700; src: url("file://{FONT_BOLD}"); }}
@page {{ size: A4; margin: 18mm; }}
body {{ font-family: NT, sans-serif; font-size: 13pt; line-height: 1.6; color: #111; }}
h1 {{ font-size: 22pt; margin: 0 0 6pt; }}
h2 {{ font-size: 15pt; margin: 14pt 0 4pt; }}
.small {{ font-size: 10pt; color: #555; }}
table {{ border-collapse: collapse; width: 100%; margin: 10pt 0; }}
th, td {{ border: 1px solid #444; padding: 5pt 8pt; text-align: left; }}
th {{ background: #e8e8e8; }}
.right {{ text-align: right; }}
.break {{ break-after: page; }}
"""


def chromium() -> str:
    found = os.environ.get("CHROMIUM") or shutil.which("chromium") or shutil.which("chrome")
    if found:
        return found
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    for pattern in ("chromium-*/chrome-linux*/chrome", "chromium-*/chrome-win/chrome.exe"):
        hits = sorted(glob.glob(f"{root}/{pattern}"))
        if hits:
            return hits[-1]
    raise SystemExit("Chromium not found: set CHROMIUM to its path")


def native_pdf(body: str, target: Path, lang: str = "te") -> None:
    """Typeset `body` (HTML) to a PDF with a text layer."""
    document = (
        f'<!doctype html><html lang="{lang}"><meta charset="utf-8"><style>{CSS}</style>'
        f"<body>{body}</body></html>"
    )
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(document, encoding="utf-8")
        subprocess.run(  # noqa: S603
            [
                chromium(),
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={target}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
        )


def pages(*bodies: str) -> str:
    return '<div class="break"></div>'.join(bodies)


# ---------------------------------------------------------------------------- images


def rasterize(pdf: Path, dpi: int) -> list[np.ndarray]:
    with pymupdf.open(pdf) as doc:
        images = []
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            image = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)
            images.append(image[:, :, :3].copy())
        return images


def paper(image: np.ndarray, rng: np.random.RandomState, tint=(246, 244, 236)) -> np.ndarray:
    """Off-white scanner paper with a little grain, text kept dark."""
    base = np.array(tint, np.float32) / 255.0
    out = image.astype(np.float32) / 255.0 * base
    out += rng.normal(0, 0.012, out.shape).astype(np.float32)
    return np.clip(out * 255, 0, 255).astype(np.uint8)


def blur(image: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(image, (0, 0), sigma)


def speckle(image: np.ndarray, rng: np.random.RandomState, amount: float) -> np.ndarray:
    mask = rng.random_sample(image.shape[:2]) < amount
    out = image.copy()
    out[mask] = rng.randint(0, 120, (int(mask.sum()), 1))
    return out


def rotate(image: np.ndarray, degrees: float, fill=(244, 242, 234)) -> np.ndarray:
    pil = Image.fromarray(image)
    return np.array(pil.rotate(degrees, expand=True, resample=Image.BICUBIC, fillcolor=fill))


def downscale(image: np.ndarray, factor: float) -> np.ndarray:
    small = cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_LINEAR)


def stamp(image: np.ndarray, text: str, angle: float = 18) -> np.ndarray:
    """A red rubber-stamp overlay, in Telugu."""
    pil = Image.fromarray(image).convert("RGBA")
    layer = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    font = ImageFont.truetype(str(FONT_BOLD), pil.width // 11)
    draw = ImageDraw.Draw(layer)
    width = draw.textlength(text, font=font)
    x, y = pil.width * 0.52, pil.height * 0.62
    draw.rectangle(
        (x - 20, y - 10, x + width + 20, y + font.size * 1.6), outline=(200, 40, 40, 190), width=8
    )
    draw.text((x, y), text, font=font, fill=(200, 40, 40, 190))
    layer = layer.rotate(angle, resample=Image.BICUBIC, center=(x, y))
    return np.array(Image.alpha_composite(pil, layer).convert("RGB"))


def watermark(image: np.ndarray, text: str) -> np.ndarray:
    pil = Image.fromarray(image).convert("RGBA")
    layer = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    font = ImageFont.truetype(str(FONT_BOLD), pil.width // 7)
    ImageDraw.Draw(layer).text(
        (pil.width * 0.08, pil.height * 0.4), text, font=font, fill=(150, 150, 150, 70)
    )
    layer = layer.rotate(35, resample=Image.BICUBIC)
    return np.array(Image.alpha_composite(pil, layer).convert("RGB"))


def scribble(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    out = image.copy()
    h, w = out.shape[:2]
    for _ in range(3):
        points = np.cumsum(rng.randint(-40, 60, (14, 2)), axis=0) + [int(w * 0.12), int(h * 0.82)]
        cv2.polylines(out, [points.astype(np.int32)], False, (40, 40, 160), 4, cv2.LINE_AA)
    return out


def scan_pdf(images: list[np.ndarray], target: Path, dpi: int, jpeg_quality: int = 80) -> None:
    """Images only, one per page: a PDF with no text layer."""
    doc = pymupdf.open()
    for image in images:
        h, w = image.shape[:2]
        page = doc.new_page(width=w * 72 / dpi, height=h * 72 / dpi)
        buffer = io.BytesIO()
        Image.fromarray(image).save(buffer, "JPEG", quality=jpeg_quality, dpi=(dpi, dpi))
        page.insert_image(page.rect, stream=buffer.getvalue())
    doc.save(target, deflate=True)
    doc.close()


# ---------------------------------------------------------------------------- content

LETTER = """
<h1>తెలుగు సాహిత్య సంఘం</h1>
<div class="small">హైదరాబాద్ · కార్యాలయ లేఖ</div>
<p>తేదీ: 14-10-2026</p>
<p>గౌరవనీయులైన శ్రీ రామారావు గారికి,</p>
<h2>విషయం: వార్షిక సమావేశ ఆహ్వానం</h2>
<p>మా సంఘం వార్షిక సమావేశం ఈ నెల ఇరవై ఆరవ తేదీన హైదరాబాద్&zwnj;లో జరుగుతుంది.
తమరు తప్పక హాజరు కావాలని కోరుకుంటున్నాము.</p>
<p>ధన్యవాదాలతో,</p>
<p><b>మీ విధేయుడు</b><br>కె. రామమూర్తి</p>
"""

INVOICE = """
<h1>లక్ష్మి స్టోర్స్</h1>
<div class="small">బిల్లు సంఖ్య: TB-2026-045 · తేదీ: 14-10-2026</div>
<p>వినియోగదారు: శ్రీ రామారావు</p>
<table>
<tr><th>వివరం</th><th class="right">పరిమాణం</th><th class="right">మొత్తం</th></tr>
<tr><td>పెసలు</td><td class="right">25 కిలోలు</td><td class="right">₹ 2,250</td></tr>
<tr><td>కందిపప్పు</td><td class="right">5 కిలోలు</td><td class="right">₹ 900</td></tr>
<tr><td>నూనె</td><td class="right">10 లీటర్లు</td><td class="right">₹ 1,800</td></tr>
<tr><td>చక్కెర</td><td class="right">10 కిలోలు</td><td class="right">₹ 1,500</td></tr>
</table>
<h2>చెల్లించవలసిన మొత్తం: ₹ 6,450</h2>
<p>ధన్యవాదాలు! మళ్ళీ రండి.</p>
"""

CONJUNCTS = """
<h1>సంయుక్తాక్షరాలు</h1>
<table>
<tr><th>అక్షరం</th><th>పదాలు</th></tr>
<tr><td>క్ష</td><td>పరీక్ష, లక్ష్మి, రక్షణ</td></tr>
<tr><td>ర్థ</td><td>విద్యార్థి, అర్థం</td></tr>
<tr><td>కృ</td><td>కృష్ణా నది</td></tr>
<tr><td>ప్ర</td><td>ప్రజలు, ప్రకృతి</td></tr>
</table>
<p>ఆంధ్రప్రదేశ్ మరియు తెలంగాణ&zwnj;లో కూడా తెలుగు మాట్లాడతారు.</p>
<p>సంవత్సరం ౨౦౨౪ (తెలుగు అంకెలు) మరియు సంవత్సరం 2024 (అంకెలు).</p>
"""

KRISHNA = """
<h1>కృష్ణా నది</h1>
<p>కృష్ణా నది భారతదేశంలో ఒక ప్రధాన నది.
ఇది పశ్చిమ కనుమలలో పుడుతుంది.</p>
"""

GODAVARI_EN = """
<h1>The Godavari River</h1>
<p>The Godavari is the second longest river in India. It flows across the Telugu states
and is a source of water for farming and drinking.</p>
"""

GODAVARI = """
<h1>గోదావరి నది</h1>
<p>గోదావరి నది తెలుగు ప్రజల జీవనాడి. ఈ నది నీరు వ్యవసాయానికి ఎంతో ఉపయోగపడుతుంది.</p>
"""

MIXED = """
<h1>Annual Meeting Notice</h1>
<p>The annual meeting of the association will be held this month.
Members are requested to attend.</p>
<h2>వార్షిక సమావేశ నోటీసు</h2>
<p>సంఘం వార్షిక సమావేశం ఈ నెల జరుగుతుంది. సభ్యులందరూ హాజరు కావాలి.</p>
<p>Venue: హైదరాబాద్ — Time: 10:30 AM — తేదీ: 26-10-2026</p>
"""

TABLE = """
<h1>విద్యార్థుల మార్కుల పట్టిక</h1>
<table>
<tr><th>క్రమ సంఖ్య</th><th>పేరు</th><th>ఊరు</th><th class="right">మార్కులు</th></tr>
<tr><td>1</td><td>రాము</td><td>విజయవాడ</td><td class="right">92</td></tr>
<tr><td>2</td><td>సీత</td><td>గుంటూరు</td><td class="right">88</td></tr>
<tr><td>3</td><td>లక్ష్మి</td><td>తిరుపతి</td><td class="right">95</td></tr>
</table>
"""

POEM = """
<h1>తెలుగు భాష మధురమైనది</h1>
<p>నా పేరు రాము.</p>
<p>అమ్మ ఇంటికి వెళ్ళింది.</p>
<p>కాకి చెట్టు మీద కూర్చుంది.</p>
"""

ENGLISH_BLOCK = """
<h1>Invoice total due</h1>
<p>The museum of art is open every day. Payment is due within thirty days of the invoice date.</p>
"""

SCAN_MIXED = (
    ENGLISH_BLOCK
    + """
<h2>తెలుగు సంస్కృతి</h2>
<p>ఆంధ్రప్రదేశ్ దాని విశిష్టమైన సంస్కృతి, సంప్రదాయాలకు ప్రసిద్ధి చెందింది.</p>
"""
)

SHORT = "<h1 style='font-size:46pt;margin-top:120pt'>తెలుగు</h1>"

NUMBERS = """
<h1 style="font-size:30pt">౧౨౩౪౫౬౭౮౯౦</h1>
<p style="font-size:20pt">12/10/2026 — 4,500.00 — 2024</p>
"""

FILENAME_DOC = """
<h1>ఇది ఒక పరీక్ష పత్రం</h1>
<p>ఫైల్ పేరు తెలుగులో ఉంది.</p>
"""


def build() -> None:
    rng = np.random.RandomState(2026)
    if OUT.exists():
        for old in OUT.glob("*.pdf"):
            old.unlink()
    OUT.mkdir(parents=True, exist_ok=True)

    def native(name: str, body: str, lang: str = "te") -> Path:
        target = OUT / name
        native_pdf(body, target, lang)
        return target

    first = native("01_Telugu_Native_Letter.pdf", LETTER)
    native("02_Telugu_Native_Invoice.pdf", INVOICE)
    native("03_Telugu_Native_Conjuncts.pdf", CONJUNCTS)
    native("04_Telugu_Native_Multipage.pdf", pages(KRISHNA, GODAVARI_EN, GODAVARI))
    native("05_Telugu_Native_Mixed_Page.pdf", MIXED, "en")
    native("06_Telugu_Native_Table.pdf", TABLE)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        def source(body: str) -> list[np.ndarray]:
            pdf = work / "page.pdf"
            native_pdf(body, pdf)
            return rasterize(pdf, 220)

        clean = [paper(i, rng) for i in source(POEM)]
        scan_pdf(clean, OUT / "07_Telugu_Scan_Clean.pdf", 220)

        mixed = [paper(i, rng) for i in source(SCAN_MIXED)]
        scan_pdf(mixed, OUT / "08_Telugu_Scan_Mixed_Lines.pdf", 220)

        order = [
            paper(source(GODAVARI_EN)[0], rng),
            paper(source(KRISHNA)[0], rng),
            paper(source(ENGLISH_BLOCK)[0], rng),
        ]
        scan_pdf(order, OUT / "09_Telugu_Scan_Mixed_Pages.pdf", 220)

        low = [blur(downscale(i, 0.35), 1.4) for i in source(POEM)]
        scan_pdf([paper(i, rng) for i in low], OUT / "10_Telugu_Scan_LowRes.pdf", 100, 55)

        poem = source(POEM)[0]
        rotated = [rotate(paper(poem, rng), -90), rotate(paper(poem, rng), 180)]
        scan_pdf(rotated, OUT / "11_Telugu_Scan_Rotated.pdf", 220)

        skewed = speckle(rotate(paper(poem, rng), 8), rng, 0.0015)
        scan_pdf([skewed], OUT / "12_Telugu_Scan_Skewed.pdf", 220)

        scan_pdf([paper(source(SHORT)[0], rng)], OUT / "13_Telugu_Scan_Short.pdf", 220)
        scan_pdf([paper(source(NUMBERS)[0], rng)], OUT / "14_Telugu_Scan_Numbers_Only.pdf", 220)
        scan_pdf([paper(source(TABLE)[0], rng)], OUT / "15_Telugu_Scan_Table.pdf", 220)

        noisy = watermark(paper(source(LETTER)[0], rng), "నమూనా")
        noisy = scribble(speckle(stamp(noisy, "రహస్యం"), rng, 0.004), rng)
        scan_pdf([noisy], OUT / "16_Telugu_Scan_Noisy.pdf", 220, 65)

    native("17_తెలుగు_పత్రం.pdf", FILENAME_DOC)
    shutil.copy(first, OUT / "18_Telugu_Duplicate_Of_01.pdf")

    with pymupdf.open(first) as doc:
        doc.save(
            OUT / f"19_Telugu_Protected_File (Pass - {PASSWORD}).pdf",
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw=PASSWORD,
            owner_pw=PASSWORD + "-owner",
        )
    # A PDF header followed by bytes that are not a PDF: nothing can be repaired from it.
    junk = np.random.RandomState(20).randint(0, 256, 2048).astype(np.uint8).tobytes()
    (OUT / "20_Telugu_Corrupted.pdf").write_bytes(b"%PDF-1.7\n" + junk)
    print(f"wrote {len(list(OUT.glob('*.pdf')))} files to {OUT}")


if __name__ == "__main__":
    build()
