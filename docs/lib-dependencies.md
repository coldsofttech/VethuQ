# Dependencies in the desktop build's `lib/`

What ends up in `build/desktop/VethuQ/lib/` (the PyInstaller onedir library folder, installed
as `{app}\lib`), why each package is there, and whether it could be dropped. A package's
`*.dist-info` folder sits in `lib/` even when its Python code is bundled inside the
executables' archive instead, so a `dist-info` entry on its own does not mean the code is
loose on disk.

Snapshot: the build has 59 `dist-info` packages and 140 top-level entries (about 607 MB).

**Status: stub.** Only the entries below are written up so far; the rest are added one at a
time.

| Column | Meaning |
|---|---|
| License | The licence declared in the package's own metadata (`License` / `License-Expression`) |
| Required by | The package that declares it as a dependency (VethuQ, or a third-party package) |
| Removable? | Whether the frozen build could leave it out without breaking VethuQ |

## Entries

| Package | Version | License | Size (dist-info) | Required by | Purpose | Removable? |
|---|---|---|---|---|---|---|
| `aistudio-sdk` | 0.3.9 | Apache-2.0 | 28 KB | `paddlex` (`Requires-Dist: aistudio-sdk>=0.3.5`), pulled in by `paddleocr` | Downloads models from Baidu AI Studio, one of the model hosters PaddleX can use | Not as-is, see below |
| `annotated-types` | 0.8.0 | MIT | 30 KB | `pydantic` 2.13.5, which `paddlex` requires | Reusable type constraints (`Gt`, `Len`, ...) that pydantic uses for field validation | No, pydantic imports it at load |
| `anyio` | 4.15.1 | MIT | 28 KB (1.4 MB code) | `httpx`, `httpcore` (and the `httpx2`/`httpcore2` packages), which `paddlepaddle` 3.3.1 and `huggingface_hub` 2.0.0 need | Async I/O layer under the HTTP client stack | No, `httpx`/`httpcore` import it |
| `ast_serialize` | 0.11.2 | MIT | 158 KB dist-info, 2.5 MB package | `mypy` 2.3.1 (dev dependency) | Native bindings that serialize mypy's parse trees | Yes, see below |
| `bce-python-sdk` | 0.9.79 | Apache-2.0 | 28 KB dist-info, 2.9 MB package (`baidubce`) | `aistudio-sdk`; also `paddlex`'s optional `serving` extra | Baidu Cloud (BOS storage and API) client, used by the AI Studio SDK | Only together with `aistudio-sdk`, see below |
| `python-bidi` | 0.6.11 | LGPL-3.0-or-later | 88 KB dist-info, 0.4 MB package (`bidi`) | `paddlex` (its `ocr`, `ocr-core` and `base` extras) | Right-to-left text reordering for Arabic OCR results | Yes for English OCR, see below |
| `certifi` | 2026.7.22 | MPL-2.0 | 19 KB dist-info, 0.25 MB package (loose in `lib/`) | `httpx`, `httpcore`, `requests` | CA certificate bundle for HTTPS | No, HTTPS downloads need it |
| `cffi` | 2.1.1 | MIT-0 | 20 KB dist-info, 0.6 MB package (`_cffi_backend` is a loose `.pyd` in `lib/`) | `cryptography`, which `modelscope_hub` requires | C foreign-function interface used by `cryptography` | With `cryptography`/`modelscope_hub` only |
| `chardet` | 7.6.0 | 0BSD | 31 KB dist-info, 2.4 MB package (loose in `lib/`) | `paddlex`, `requests` | Guesses a text file's encoding | No, `paddlex` imports it |
| `charset_normalizer` | 3.5.1 | MIT | 64 KB dist-info, 0.7 MB package (loose in `lib/`) | `requests` | Encoding detection for HTTP responses | No, `requests` imports it |
| `click` | 8.5.0 | BSD-3-Clause | 18 KB dist-info, 0.9 MB package | `aistudio-sdk`, `huggingface_hub` 2.0.0 | Command-line framework behind those packages' own CLIs | Probably, see below |
| `colorama` | 0.4.6 | BSD-3-Clause | 34 KB dist-info, 0.1 MB package | `typer` (on Windows, VethuQ's CLI framework), `tqdm`, `colorlog` | Makes ANSI colour codes work in Windows consoles | No, the CLI depends on it through `typer` |
| `colorlog` | 6.12.0 | MIT | 27 KB dist-info, 60 KB package | `paddlex` | Coloured log output | No, `paddlex` imports it |
| `crc32c` | 2.9.post0 | LGPL-2.1-or-later | 57 KB dist-info, 0.16 MB package (loose in `lib/`) | `bce-python-sdk` | CRC32C checksums for Baidu Cloud uploads | Yes, see below |

### aistudio-sdk

- **Not used by VethuQ's own code.** Nothing under `packages/` imports `aistudio_sdk`.
- **Why it is installed.** `paddlex` 3.4.3 lists it as a hard requirement, and VethuQ reaches
  `paddlex` through `paddleocr` (the OCR engine).
- **Where it is used.** `paddlex/inference/utils/official_models.py` imports
  `aistudio_sdk.snapshot_download` at the top of the file. Its AI Studio hoster class
  (`alias = "aistudio"`) calls it to download `PaddleX/<model_name>` repositories.
- **Is it used at run time?** Probably not by default. PaddleX picks its model hoster from
  `PADDLE_PDX_MODEL_SOURCE`, which defaults to `huggingface`, so the AI Studio download code
  is never called unless that variable is set to `aistudio`.
- **Why it cannot simply be removed.** The import runs when `official_models` loads, so
  excluding the package from `vethuq.spec` makes the OCR engine fail on import. Dropping it
  would need a stub module in its place. It is tiny, so this is not worth doing on size
  alone.


### ast_serialize

- **Not used by VethuQ at run time.** It is a dependency of `mypy`, the type checker in the
  repo's `dev` dependency group (`pyproject.toml`).
- **Why it is in `lib/`.** The PyInstaller analysis includes `pydantic.mypy` (pydantic's mypy
  plugin), which imports `mypy`, and `mypy` imports `ast_serialize`. I have not confirmed what
  pulls `pydantic.mypy` in; it is likely pydantic's PyInstaller hook collecting all its
  submodules.
- **Removable.** Nothing in VethuQ needs a type checker at run time, so `mypy`,
  `pydantic.mypy` and `ast_serialize` can go in the `excludes` of `vethuq.spec`. Untested.

### bce-python-sdk

- **Not used by VethuQ's own code.** The Python module is `baidubce`.
- **Why it is installed.** `aistudio-sdk` imports it (`aistudio_sdk/utils/bos_sdk.py` and the
  dataset and pipeline modules) to talk to Baidu Cloud storage. `paddlex` also lists it for its
  optional `serving` extra, and `paddlex`'s Qianfan retriever imports it, which VethuQ never uses.
- **Removable.** Only if `aistudio-sdk` is dropped with it (see above). Its package code is not
  in `lib/` as loose files, only the `dist-info` folder.

### python-bidi

- **Not used by VethuQ's own code.**
- **Where it is used.** `paddlex/inference/models/text_recognition/predictor.py` imports
  `bidi.algorithm.get_display` and applies it only to the two Arabic recognition models
  (`arabic_PP-OCRv3_mobile_rec`, `arabic_PP-OCRv5_mobile_rec`). English OCR (VethuQ's only
  language at the moment) never reaches that code.
- **Licence note.** It is LGPL-3.0-or-later (`COPYING` and `COPYING.LESSER` in its metadata),
  unlike the permissive licences of the others so far. It is a separate package in `lib/`, not
  linked into VethuQ's own code, and it is already listed in the installer's
  third-party license summary (`installer/LICENSE.md`).
- **Removable.** Probably, for English only. The import is guarded by `is_dep_available`, but
  the class is decorated with `@class_requires_deps("python-bidi")`, so check that the English
  text recogniser still loads without it. Untested.

### certifi

- **Not used by VethuQ's own code.** It supplies the trusted root certificates for HTTPS to
  `httpx`, `httpcore` and `requests`, i.e. the model downloads.
- **Licence note.** MPL-2.0 (weak copyleft, file level). Unmodified, so VethuQ's own code is
  not affected.

### cffi

- **Not used by VethuQ's own code.** Its only requirer is `cryptography`, which comes from
  `modelscope_hub` (the ModelScope model hoster, which VethuQ does not use by default).
- **Removable.** Only along with `cryptography` and `modelscope_hub`; not tried.

### chardet and charset_normalizer

- **Not used by VethuQ's own code.** Two packages doing the same job, both required.
- **`chardet`.** `paddlex/utils/file_interface.py` imports it to detect the encoding of
  text files it reads, and `requests` can use it too.
- **`charset_normalizer`.** `requests` requires it for response decoding.
- **Removable.** Neither, while `paddlex` and `requests` stay.

### click

- **Not used by VethuQ's own code.** VethuQ's CLI uses `typer`, which no longer needs it here.
- **Why it is installed.** The command-line modules of `aistudio-sdk` (`aistudio_sdk/cmdline.py`)
  and `huggingface_hub` (`huggingface_hub/cli/`) import it for their own `aistudio` and `hf`
  commands. VethuQ never runs those.
- **Removable.** Probably, along with those CLI modules, which are not on VethuQ's path. Untested.

### colorama and colorlog

- **`colorama`.** `typer` requires it on Windows, so VethuQ's own CLI needs it; `tqdm` (progress
  bars) and `colorlog` use it too. Keep.
- **`colorlog`.** `paddlex/utils/logging.py` imports it at the top, to colour PaddleX's log
  lines. Required while `paddlex` is.

### crc32c

- **Not used by VethuQ's own code.**
- **Why it is installed.** `bce-python-sdk` (`baidubce/utils.py`) imports it inside a
  `try`/`except ImportError`, falling back to a slower pure-Python path, so it is optional there.
- **Licence note.** LGPL-2.1-or-later, the second LGPL entry after `python-bidi`; it is already
  listed in the installer's third-party license summary (`installer/LICENSE.md`). It ships as
  loose files in `lib/` (its own folder with a compiled extension).
- **Removable.** Yes, with no loss of function, if `bce-python-sdk` stays (see above). It could
  be excluded in `vethuq.spec` to drop an LGPL component. Untested.

## To add

- The remaining 58 `dist-info` packages and the large non-Python entries (Paddle's native
  libraries and models), with their sizes.
- A "required by" tree built from each package's `METADATA`.
