# Releasing to PyPI

Three packages are released from this repository, each by pushing its own tag. Versions are independent
and come from the tag (hatch-vcs).

| Tag | Package | Wheels |
|---|---|---|
| `vethuq-addon-api-vX.Y.Z` | `vethuq-addon-api` | one pure-Python wheel and an sdist |
| `vethuq-worker-vX.Y.Z` | `vethuq-worker` | one pure-Python wheel and an sdist |
| `vethuq-vX.Y.Z` | `vethuq` | a wheel per platform: Linux x86_64 and arm64, Windows amd64 (no sdist) |

    git tag vethuq-worker-v1.2.0 && git push origin vethuq-worker-v1.2.0

Add `-rcN` (`vethuq-v1.0.0-rc1`) for a release candidate: it goes to TestPyPI only.

The command line, the interactive shell, the background service and the worker ship as installers: see
[Command-line installers](#command-line-installers).

## What the workflow does (`.github/workflows/release.yml`)

1. **plan** reads the tag (`scripts/release/plan.py`);
2. **verify** runs ruff and the package's tests against the sibling premium and entitlements checkouts;
3. **build**: `uv build --no-sources`, so the workspace's path sources never reach the published
   metadata; the built version must equal the tag's. For `vethuq`, see below;
4. **smoke** (`vethuq` only) installs the wheel of each platform and imports `vethuq` and
   `vethuq_entitlements`. Because it installs from PyPI, it also proves the free add-ons `vethuq`
   depends on are already published;
5. **publish** waits for approval of the `pypi` (or `testpypi`) environment, then uploads with Trusted
   Publishing (no token is stored);
6. **github-release** attaches the files to a release with the CHANGELOG section as notes.

## `vethuq` carries the entitlements runtime

Licensed add-ons check their licence with `vethuq_entitlements`, which is not on PyPI. They do not
depend on it; the `vethuq` wheel provides it. For each platform, the workflow downloads the matching
compiled `vethuq-entitlements` wheel from the private VethuQ-entitlements release named in
`packages/core/ENTITLEMENTS_VERSION` (checking `SHA256SUMS`) and merges it into the pure `vethuq` wheel
(`scripts/release/merge_wheel.py`), giving `vethuq-X-cp311-abi3-<platform>.whl`. So `vethuq` has
platform wheels only: no macOS, and no sdist.

To pick up a new runtime: release it in VethuQ-entitlements, change `ENTITLEMENTS_VERSION`, then release
`vethuq`.

## Order

`vethuq-addon-api` first; then the add-ons and bundles in VethuQ-premium that `vethuq` depends on and
that its extras name (see that repository's `docs/releasing.md`); then `vethuq`; `vethuq-worker`
whenever the GitHub tier's protocol changes.

## One-time set-up

- PyPI and TestPyPI: for `vethuq`, `vethuq-addon-api` and `vethuq-worker`, add a trusted publisher
  (this repository, workflow `release.yml`, environment `pypi`, or `testpypi` on TestPyPI).
- Repository settings: create the `pypi` and `testpypi` environments with required reviewers.
- Secret `PREMIUM_READ_TOKEN`: read access to VethuQ-premium and VethuQ-entitlements (it is already used
  by the test workflow).

## Command-line installers

`vethuq-cli-vX.Y.Z` (`-rcN` for a release candidate) builds the command line only, with no desktop app,
interactive shell or background service, and attaches the installers to a GitHub release
(`.github/workflows/release-cli.yml`). Nothing goes to PyPI.

| Platform | File | Made with |
|---|---|---|
| Windows | `VethuQ-CLI-Setup.exe` | PyInstaller, then Inno Setup (`packages/cli/installer/vethuq-cli.iss`) |
| Linux | `vethuq-cli_X.Y.Z_amd64.deb` | PyInstaller, then `dpkg-deb`; installs to `/opt/vethuq`, with `/usr/bin/vethuq` |

Both hold the same folder:

    vethuq(.exe)   the command (vethuqic(.exe), the interactive shell, joins it; see below)
    lib/           the Python runtime and every dependency (Paddle, rich, SQLAlchemy, ...)
    add-ons/       the default add-ons, one folder each: english, pdf, txt, csv, markdown, paddle,
                   ocr-quick, like, exact, full-text, case, unicode

`add-ons/` holds each add-on's package and its dist-info; a runtime hook puts each folder on `sys.path`,
which is where VethuQ finds add-ons by their entry points. The other add-ons (`lexical`, `proximity`,
`fuzzy`, `noise-fuzzy`, `leetspeak`, `semantic`, ...) are not in the installers. The Paddle OCR models are
downloaded the first time OCR runs.

Build one locally (Windows needs Inno Setup's `iscc` on PATH; Linux needs `dpkg-deb`), from a workspace
next to a `VethuQ-premium` checkout, with the compiled `vethuq_entitlements` installed:

    uv sync --package vethuq-cli --package vethuq-interactive-cli --package vethuq-background --package vethuq-worker --no-dev
    uv pip install "pyinstaller>=6.10"
    uv run --no-sync python scripts/release/release.py --cli --version 1.2.0

`--dev` skips compression and reuses an unchanged PyInstaller build. After changing the icon, run
`python scripts/dev/brand/cli_installer.py` to regenerate the images and license page, which both
installers share in `installer/shared/` (with the icon and the add-ons runtime hook).

### The interactive shell

`vethuq-interactive-cli-vX.Y.Z` (`-rcN` for a release candidate) builds the interactive shell,
`vethuqic`, with `.github/workflows/release-interactive-cli.yml`. It installs **into the command
line's folder** and reuses its `lib/` and `add-ons/`, so it has no copy of its own: the same
PyInstaller build makes `vethuq` and `vethuqic`, which share `lib/`.

| Platform | File | Installs |
|---|---|---|
| Windows | `VethuQ-Interactive-CLI-Setup.exe` | `vethuqic.exe` into the folder `VethuQ-CLI-Setup.exe` chose, plus a Start menu entry and the PATH task |
| Linux | `vethuq-interactive-cli_X.Y.Z_amd64.deb` | `/opt/vethuq/vethuqic`, `/usr/bin/vethuqic`, a `.desktop` launcher (`Terminal=true`) and icons; depends on `vethuq-cli` |

Install the command line first. Both installers refuse to run otherwise, and refuse a command line
built from different libraries: `lib/runtime-id.txt` (a hash of `uv.lock`, the Python minor version and the
PyInstaller version) must equal the id the shell's installer was built with. So release the two from the
same commit or at least the same `uv.lock`. Uninstalling the command line removes `vethuqic` too. The
Windows shell's own uninstaller removes only what it added (`vethuqic.exe`).

    uv sync --package vethuq-cli --package vethuq-interactive-cli --package vethuq-background --package vethuq-worker --no-dev
    uv run --no-sync python scripts/release/release.py --cli --interactive-cli --version 1.2.0

### The background service

`vethuq-background-service-vX.Y.Z` (`-rcN` for a release candidate) builds the background service,
`vethuqbs`, with `.github/workflows/release-background-service.yml`. Like the shell it installs **into the
command line's folder**, so `vethuq.exe`, `vethuqic.exe` and `vethuqbs.exe` sit side by side on one `lib/`
and `add-ons/`, and it needs the command line installed first, from the same build (`runtime-id.txt`).

| Platform | File | Installs |
|---|---|---|
| Windows | `VethuQ-Background-Service-Setup.exe` | `vethuqbs.exe`, and the `vethuq background` commands in `add-ons\background` |
| Linux | `vethuq-background-service_X.Y.Z_amd64.deb` | `/opt/vethuq/vethuqbs`, `/usr/bin/vethuqbs`, `/opt/vethuq/add-ons/background`; depends on `vethuq-cli` |

`vethuqbs` is what runs: `vethuqbs --service --db FILE`. On Windows it hosts itself in the service manager
(pywin32), and `vethuq background install` registers it with `sc.exe create` (asking for administrator
rights and the account to run as); on Linux the `systemd --user` unit's `ExecStart` is the same command.
**Setup does not create the service**: that is a choice (account, password, which database). Setup does stop
it while it replaces `vethuqbs.exe` and start it again, and uninstalling Setup removes the service.

The `vethuq background ...` commands (install, uninstall, start, stop, pause, resume, status) are the package
`vethuq_background`, shipped with its entry point in `add-ons/background`: `vethuq` and `vethuqic` find them
there, so they appear once this is installed. Uninstalling the command line removes `vethuqbs.exe` too, so
uninstall the service first (the background service's own uninstaller does).

    uv sync --package vethuq-cli --package vethuq-interactive-cli --package vethuq-background --package vethuq-worker --no-dev
    uv pip install "pywin32>=306"        # Windows only
    uv run --no-sync python scripts/release/release.py --background-service --version 1.2.0

### The worker

`vethuq-worker-bin-vX.Y.Z` (`-rcN` for a release candidate) builds the worker program, `vethuqw`, with
`.github/workflows/release-worker.yml`. (`vethuq-worker-vX.Y.Z` is the PyPI package's tag and is
unchanged.) Like the shell and the service it installs **into the command line's folder** on the same
`lib/` and `add-ons/`, and needs the command line installed first, from the same build.

| Platform | File | Installs |
|---|---|---|
| Windows | `VethuQ-Worker-Setup.exe` | `vethuqw.exe` |
| Linux | `vethuq-worker_X.Y.Z_amd64.deb` | `/opt/vethuq/vethuqw`, and `/usr/bin/vethuq-worker` pointing at it; depends on `vethuq-cli` |

    vethuqw run --job-id ID --payload DIR --out DIR      # the key is in VETHUQ_MASTER_KEY
    vethuqw bake-models --models DIR                     # fetches the OCR models (needs the network)

The worker reads a job with the add-ons in `add-ons/`: the installers carry the free defaults, so a runner
that needs more (office files, Telugu, deeper OCR) adds those add-on folders there. The OCR models are not
in the installers; `bake-models` downloads them, and `VETHUQ_MODELS` points the worker at them. There is
nothing to configure at install time and no service to clean up; uninstalling the command line removes
`vethuqw.exe` too.

    uv sync --package vethuq-cli --package vethuq-interactive-cli --package vethuq-background --package vethuq-worker --no-dev
    uv run --no-sync python scripts/release/release.py --worker --version 1.2.0
