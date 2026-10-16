# OCR accuracy regression suite

Pages are rendered from known text, degraded the way scans and photos are, read by every installed
OCR phase with the real engine and models, and scored. Limits per phase and page type in
`thresholds.json` turn a drop in accuracy into a failing run.

    uv run python -m tools.ocr_accuracy --out report.json --summary summary.md
    uv run python -m tools.ocr_accuracy --phases quick --pages clean,scan
    uv run python -m tools.ocr_accuracy --suggest suggested.json

It exits with status 1 when a case fails. The first run downloads the OCR models; the whole suite
takes 10 to 20 minutes (the deep phase reads many angles), so it is not part of `test.yml`. The
`ocr-accuracy` workflow runs it weekly and on demand, and can be called before a release; it uploads
the JSON report and suggested limits as an artifact and writes the table to the step summary. The
suite's own unit tests (scorer, page generator, runner, with a fake reader) run in `test.yml`.

## What is measured

| Page type | What it is |
|---|---|
| `clean` | black text on white, A4 at 150 dpi |
| `scan` | blur, grain and JPEG compression, like a flatbed scan |
| `skew` | the page 5 degrees off square |
| `poor` | low resolution, low contrast, noisy, heavily compressed |
| `photo` | a phone photo: perspective, uneven light, blur |
| `rotated` | upside down (only the moderate and deep phases read turned pages) |
| `small` | small type (18 px on A4 at 150 dpi) |
| `numbers` | an invoice-like page of figures |
| `large` | A4 at 300 dpi, the size that must not run out of memory |

For each case the report has the CER (character error rate, whitespace ignored), the exact word
recall, the engine's confidence, the time and the process's peak memory so far (a high-water mark,
so it only rises). A later phase reads the angles of the earlier ones too and keeps the read with the
highest confidence, as indexing does. A read that raises (an out-of-memory error, say) fails its
case. A case with no limit is only reported (`unchecked`); a missing font skips it.

## Limits

`thresholds.json` is **provisional**: the English limits are starting values that were not measured
against the real engine, so the report says so while `"provisional": true`. Run the workflow, look at
the report, and replace the limits with the reviewed values from `--suggest` (today's score with
room: CER times 1.5 plus 0.01, word recall minus 0.05), then set `provisional` to `false`. Do not
loosen a limit to hide a regression; do not treat a case without a limit as a failure.

Known limits: Telugu on low-resolution, low-contrast pages is unreadable for every profile, so the
Telugu page types get no limit for `poor` when they are added; that is not a regression.

## Adding to it

- **A page type**: write a function from the clean image (and a seed) to the degraded one in
  `pages.py`, add it to `DEGRADE`, add a case for it in the tests, and give it limits per phase in
  `thresholds.json`.
- **A language**: add its lines to `PROSE` and `NUMBERS` and its font files to `FONTS` in `pages.py`
  (or point `VETHUQ_ACCURACY_FONT_<LANG>` at a font file). A script that needs shaping, such as
  Telugu, needs a Pillow built with Raqm, and its limits are set from a measured run.
- **Real scans and photos** with reference text (public domain or made for the purpose) are not part
  of the suite yet; they belong in a `fixtures/` folder beside a reference file per image.

Needs Pillow and NumPy (in the dev group); `rapidfuzz` is used when installed and is not required.
