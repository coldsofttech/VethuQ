# Contributing to VethuQ

This repository is the public part of VethuQ. The add-ons (file types, languages, OCR engines, search
engines, tiers) and the licence package live in two private repositories, `VethuQ-premium` and
`VethuQ-entitlements`. You can work on a good part of VethuQ without them; this page says which part,
and how the maintainer works with all three.

## Without the private repositories

Everything below needs only a clone of this repository and Python 3.11 or newer. No token, no sibling
checkout.

| What | How |
|---|---|
| Lint and format | `uvx ruff@0.6.9 check .` and `uvx ruff@0.6.9 format --check .` (what the `lint` workflow runs) |
| Add-on API tests | `pip install ./packages/addon-api pytest`, then `pytest packages/addon-api/tests` |
| Worker tests | `pip install "./packages/worker[images]" pytest pyyaml`, then `pytest packages/worker/tests` |

Install the packages from a plain virtual environment (`python -m venv`), not with `uv sync`: the
workspace resolves the premium add-ons from sibling folders (see below), so `uv sync` fails without
them. If the build complains about the version of a package installed from a clone, set
`SETUPTOOLS_SCM_PRETEND_VERSION=0.11.0`.

Add-ons are tested on the fake host that ships with the add-on API: `vethuq_addon_api.testing`
(`FakeHost`, `FakeCredits`, `FakeEngine`, `FakeReader`, `FakeExecutor`, `FakeNormalizer`). Use it
for your own add-on's tests instead of importing core or relying on private wheels.

## What needs the private repositories

`core`, `cli`, `interactive-cli`, `background`, `api` and `desktop` depend on the free add-ons (English,
PDF, text, CSV, Markdown, the Paddle engine, quick OCR, ...), which are built in `VethuQ-premium`, and
on `vethuq-entitlements`. Their tests, and the CI `test` workflow, need those checkouts: the workflow
reads them with the `PREMIUM_READ_TOKEN` secret, so it does not run for pull requests from forks.
A pull request from a fork is still checked by the `lint` workflow, which needs nothing private, and
a maintainer runs the rest.

If your change touches one of those packages, say so in the pull request and describe how you
checked it; a maintainer will run the full tests.

## Maintainer setup

Clone the three repositories next to each other, with these folder names:

```
VethuQ/                  # this repository
VethuQ-premium/          # the add-ons and bundles
VethuQ-entitlements/     # the licence package
```

Then, in `VethuQ`:

```sh
uv run python scripts/dev/sync.py     # uv sync --all-packages --group dev
uv run pytest packages/core/tests -m "not integration"
```

`[tool.uv.sources]` in `pyproject.toml` points at the sibling folders as **editable** installs, so a
change in `VethuQ-premium` is seen here at once. Editable installs are the default way to work: the
compiled (Cython) wheels that ship to users are built for releases and for the compiled test run, not
for everyday development. To build one locally you need a C compiler (MSVC Build Tools on Windows);
the premium repository's `docs/development.md` explains the build, the wheel gate that checks the
result, and the add-on layout checks (`scripts/add-ons/check_addons.py`).

Run `uv run pre-commit install` once to get the commit-time checks (ruff, hygiene hooks, key
detection, pytest).

## Pull requests

- Keep a change to one concern, with tests.
- Run the lint commands above before you push; the `lint` workflow runs them on every pull request.
- Add a line to the changelog of the package you changed.
