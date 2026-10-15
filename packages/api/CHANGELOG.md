# Changelog

All notable changes to `vethuq-api`.

## [Unreleased]

### Added (INI, SQL, reStructuredText, log)
- `/api/files/ini`, `/sql`, `/rst` and `/log` return a file's source for the code preview, like the other text file types.

### Added (TOML)
- `/api/files/toml?path=` returns a TOML file's source for the code preview, like the other text file types.

### Added (RSS)
- `/api/files/rss?path=&at=` returns a feed for the feed preview: its head lines and a window of at most 500 entries around the character `at` (the match) of the indexed text, each line with its kind and its offset in that text. Needs `defusedxml` (the RSS add-on brings it); a feed that is not well-formed is read as loose text, as the add-on does, and a test holds the two together.

### Added (SVG)
- The preview shows an SVG drawing (`/api/files/svg?path=`) as it is, served under a sandboxing policy (`Content-Security-Policy: sandbox; default-src 'none'...`) so its scripts cannot run if the address is opened on its own; a compressed `.svgz` is sent with `Content-Encoding: gzip`. A response that sets its own Content-Security-Policy now keeps it.

### Added (JPEG 2000)
- The picture preview shows a JPEG 2000 (`/api/files/jp2?path=`) as a PNG, with transparency laid on white as OCR sees it.

### Added (HEIC)
- The picture preview shows a HEIC (`/api/files/heic?path=&page=`) as a PNG, one picture at a time, the primary first, as the HEIC add-on reads them (checked picture for picture). Needs `pillow-heif` (the HEIC add-on brings it); without it the preview says so. A picture over Pillow's pixel limit is refused, as pillow-heif makes no such check.

### Added (picture preview)
- `GET /api/files/png`, `/jpg` and `/tiff` (`?path=`) serve a picture of a source: JPEG and PNG as they are, a TIFF frame (`page`, from 1) as a PNG, turned upright and brought to 8-bit colour. A frame over 40 megapixels is refused. `GET /api/files/text` also serves the text OCR read from these pictures.

### Added (JSON, YAML, JavaScript and XML previews)
- `GET /api/files/json`, `/yaml`, `/js` and `/xml` (`?path=`) return a file of a source as it is on disk, like the CSS and web page routes now do through one shared handler, for the code preview.

### Added (web page preview)
- `GET /api/files/html?path=` returns a web page of a source as it is on disk, for the preview (the index keeps only what a reader sees).

### Added (CSS preview)
- `GET /api/files/css?path=` returns a stylesheet of a source as it is on disk (the index re-flows it to a rule a line) with its longest line, for the code preview. The Markdown route now shares the reading code and the 100 MB limit.

### Added (Markdown preview)
- `GET /api/files/markdown?path=` returns a Markdown file of a source as it is on disk (the index keeps only its words, without the markup), up to 100 MB, for the rendered preview.

### Added (WebP preview)
- `GET /api/files/webp?path=&page=` serves page `page` (from 1) of a WebP of a source as a PNG, the pages being the add-on's (a still is one page, an animation one for each distinct picture), with transparency laid on white and the EXIF orientation applied as for OCR.

### Fixed (damaged pictures)
- A cut-off or damaged BMP, GIF, WebP or TIFF now always gives a readable 422 from the picture routes. Pillow's plugins raise an assortment of errors for such files (an `IndexError`, a `TypeError`, a `struct.error`...); some of them were unhandled server errors, among them one raised while counting a TIFF's frames. A picture Pillow only warns about (over its pixel limit but under twice it) is refused too.

### Added (GIF preview)
- `GET /api/files/gif?path=&page=` serves page `page` (from 1) of a GIF of a source as a PNG: the picture a viewer shows at that point of the animation, with transparency laid on white as OCR sees it. The pages are the GIF add-on's (the distinct pictures of the animation), so "frame 2 of 3" is the picture that was read. A frame over 40 megapixels is refused.

### Added (BMP preview)
- `GET /api/files/bmp?path=` serves a BMP (or DIB) of a source as a PNG in ordinary 8-bit colour, so a run-length encoded, OS/2 or headerless one is drawn by every browser; a 32-bit one whose alpha bytes are all zero is shown opaque, not blank. A picture over 40 megapixels is refused. A BMP or TIFF that is damaged, cut off or not a picture now gives a readable 422 (it was an unhandled error).

### Added (web archive preview)
- `GET /api/files/mhtml?path=` turns an MHTML web archive of a source into one page for the preview: `rendered` is the page with every reference the archive can answer put in (pictures and fonts as `data:` addresses, stylesheets as `<style>` blocks, `@import`s followed, saved frames as `srcdoc`), so the sandboxed frame shows it without fetching anything or running a script; `text` is the page's HTML as written, with the pages saved inside it after, for the source views. Up to 24 MB of pictures and styles are put in (`incomplete` says if there were more), and frames nest three deep. The page preview shows it like an HTML file, and marks the words in a saved frame too.

### Added (NDJSON preview)
- `GET /api/files/ndjson?path=` returns an NDJSON (JSON Lines) file of a source as it is on disk (up to 100 MB), for the code preview, like the JSON, YAML and XML routes.

### Added (Parquet table preview)
- `GET /api/files/parquet?path=` returns a window of rows of a Parquet table of a source, in the same reply as the CSV and TSV routes (sorting, filtering, where a match is). The column names are the header (row 1, as in the index) and the rows are those the Parquet add-on indexed, up to the text it indexes (`truncated` says if the table was cut there). It needs PyArrow, which the Parquet add-on brings.

### Added (TSV table preview)
- `GET /api/files/tsv?path=` returns a window of rows of a TSV file of a source, the same reply as `/api/files/csv` (sorting, filtering, header, where a match is) with a tab as the only delimiter. Only a TSV file of a source can be shown (the `tsv` file type must be installed); the CSV route does not take TSV files.

### Added (CSV table preview)
- `GET /api/files/csv?path=` returns a window of rows of a CSV file of a source, read from disk (the same rows VethuQ indexed: empty rows left out, the delimiter and encoding detected), with the header (guessed), column widths and, for `at_row`/`at_offset`, the position of the matching row and cell. `sort`, `dir`, `filter`, `column` and `header` shape the view on the server. Files over 64 MB are refused.

### Added (text preview)
- `GET /api/files/text?document_id=&page=&start=&count=` returns a window of lines (at most 500) of a text or Markdown file as it was indexed, with the total, for the text preview. Lines over 10,000 characters are clipped.

### Added (PDF preview)
- `GET /api/files/pdf?path=` serves a PDF of a source inline, with ranges, for the in-app viewer. Only a PDF VethuQ reads, inside an active source. The content security policy gains `worker-src 'self'` (pdf.js runs in a worker served by the app).

### Changed (opening at the place)
- `POST /api/os/open` accepts `page`, `line` and `column` and returns `{opened, jumped, hint}`.

### Added
- Search: `/api/search/options` (engines, normalizers, file types and the saved defaults), `/api/search/run` (file
  types, sources, languages, engine, case, normalizer levels, engine options, paging) and `/api/search/export`
  (every match as JSON or HTML). `/api/os/open` opens a file of a source in its own application; it only opens a
  file of a kind VethuQ reads inside one of the sources.
- Shared usage metrics: `/api/metrics` (where sharing stands), `/api/metrics/preview` (exactly the batch that would be
  sent, with its size), `/api/metrics/send` and `/api/metrics/delete-data`.
- GitHub token: it can be saved in the operating system's credential store (Windows Credential Manager) through the
  GitHub add-on, kept for the session only, or forgotten (`/api/github/token`, `/api/github/token/forget`).
- Logs: `/api/logs` (the files), `/api/logs/<component>` (a day's entries, filtered, with a cursor so the
  interface can follow) and `/api/logs/<component>/export`.
- Maintenance: the database check, update status and check, the signed policy, the search index (status and
  rebuild) and the processing tiers (`/api/db`, `/updates`, `/policy`, `/search-index`, `/tiers`), with slow work
  on background tasks.
- GitHub tier: `/api/github/*` (availability, the runner's setup, status, update and removal, the jobs sent to
  GitHub, and a token kept in memory for the session only). The GitHub add-on is imported only when asked.
- Add-ons: `/api/addons` (installed add-ons with status, update announced by the signed policy, licence entered,
  and the packs VethuQ names as extras), turning one off or on, and installing a pack or updating an add-on with
  pip on a background job. Only VethuQ's own pack names and announced updates reach pip; a packaged copy refuses.
- OCR: `/api/ocr` (engines and phases), `/api/ocr/models` (with size on disk), a background download job
  with progress (`/api/ocr/models/download`, `/redownload`, `/api/ocr/job`) and removal (`/clear`, `/clean`).
- Statistics: `/api/stats/summary` (totals and pages per day), `/api/stats/breakdown` (grouped, filtered, sorted
  and paged, with a totals row) and `/api/stats/export`.
- Sources and their files carry what they cost (`credits`), and files sort by it.
- Credits: `/api/credits/*` (summary for the status bar, wallets with lifetime totals, grants, usage by
  day, source or file, the daily series per wallet, the ledger, CSV/JSON exports, and redeeming a licence).
- Sources and indexing: `/api/sources` (list, add, remove, restore, delete for good, languages, files with
  filter, sort and paging from a short-lived scan, CSV/JSON export) and `/api/index/*` (state, refresh,
  start, pause, resume, stop, history, remote jobs, queued requests). A run goes to the background
  service's queue when one is working, else it runs on a thread inside the application. The Windows
  service is probed read-only (`sc query`) for the status bar, and `/api/service/<action>` controls it.
  `/api/dialog/file`, `/api/os/reveal`, and `/api/window/close` that holds back while a one-off run is going.
- The Flask application for the user interface: `create_app()`, a one-time start-up token that is
  exchanged for a session cookie, Host and Origin checks, a strict Content-Security-Policy, the
  `/api/health`, `/api/about`, `/api/platform` and `/api/window/*` endpoints, and serving of the built
  React interface.
- Settings endpoints, starting with the `indexing` section: index workers, retries, stability wait and
  stale-lock handling, OCR depth and GPU use. `/api/brand` and `/api/catalog` for the app's name and
  colours and for what is installed.
- Settings sections `general` (default languages, usage metrics), `sources` (removed-source retention),
  `tiers` (default processing tier, hybrid OCR phases and size rule, remote job limits, wait timeout) and
  `results` (confidence bands), with list, multi-choice and three-number (`bands`) setting types.
- Settings: the update check (with the skipped version and snooze shown read-only and clearable) in
  `general`, and a `system` section with log level and retention and the database integrity check.
- Settings: a `search` section (default engine, context, export format, the normalizers, each engine's
  own options), the data and backups folders (with moving the data), a section for the settings
  add-ons declare (`addons`), setting groups, and `GET /api/support-info` for a support report.
  `POST /api/dialog/folder` shows the host's folder picker where there is one.
