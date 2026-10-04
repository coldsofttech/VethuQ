VETHUQ LICENSE
==============

VethuQ is licensed under the MIT License. It also includes third-party software,
each under its own license, listed after it with how VethuQ uses it.

MIT License

Copyright (c) 2026 coldsofttech

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


VETHUQ PACKAGES
===============

All four are covered by the MIT License above.

  vethuq - MIT
      How VethuQ uses it: the public Python package and the 'vethuq' command-line program.

  vethuq-core - MIT
      How VethuQ uses it: the engine: sources, indexing, OCR pipeline, search and the local
      database.

  vethuq-cli - MIT
      How VethuQ uses it: the command-line interface.

  vethuq-ui - MIT
      How VethuQ uses it: the desktop application.


THIRD-PARTY SOFTWARE
====================

Licenses are as declared in each package's metadata. Each package remains under its
own license and copyright; its full license text is available from its project page and
in the package itself.


CORE RUNTIME (always installed)
-------------------------------


OCR engine and models

  paddlepaddle - Apache-2.0
      How VethuQ uses it: the deep-learning runtime that runs the OCR models.

  paddleocr - Apache-2.0
      How VethuQ uses it: the OCR engine: finds and reads text on scanned pages and images.

  paddlex - Apache-2.0
      How VethuQ uses it: PaddlePaddle's pipeline framework, used by PaddleOCR to load and run
      its models.

  opencv-contrib-python - Apache-2.0 (bundles FFmpeg libraries under the LGPL)
      How VethuQ uses it: decodes and prepares PNG/JPEG images and page images for OCR.

  numpy - BSD-3-Clause (also 0BSD, MIT, Zlib, CC0-1.0)
      How VethuQ uses it: array maths for image and OCR data.

  pillow - MIT-CMU
      How VethuQ uses it: image handling used by the OCR libraries.

  pypdfium2 - BSD-3-Clause and Apache-2.0 (includes PDFium and its dependencies' licenses)
      How VethuQ uses it: PDF page rendering used by the OCR libraries.

  pyclipper - MIT
      How VethuQ uses it: polygon clipping when outlining detected text regions.

  shapely - BSD-3-Clause
      How VethuQ uses it: geometry of detected text regions.

  imagesize - MIT
      How VethuQ uses it: reads image dimensions for the OCR libraries.

  opt-einsum - MIT
      How VethuQ uses it: tensor-expression optimisation used by the PaddlePaddle runtime.

  safetensors - Apache-2.0
      How VethuQ uses it: loads OCR model weight files.

  protobuf - BSD-3-Clause
      How VethuQ uses it: model file format used by the PaddlePaddle runtime.

  networkx - BSD-3-Clause
      How VethuQ uses it: graph utilities used by the PaddlePaddle runtime.

  pandas - BSD-3-Clause
      How VethuQ uses it: table handling inside PaddleX.

  ujson - BSD-3-Clause and TCL
      How VethuQ uses it: fast JSON reading and writing in the OCR libraries.

  python-bidi - LGPL
      How VethuQ uses it: orders right-to-left text in OCR results.

  py-cpuinfo - MIT
      How VethuQ uses it: detects CPU features so the OCR runtime can pick fast code paths.

  PyYAML - MIT
      How VethuQ uses it: reads PaddleX pipeline configuration files.

  ruamel.yaml - MIT
      How VethuQ uses it: reads and writes YAML configuration in PaddleX.

  pydantic - MIT
      How VethuQ uses it: validates PaddleX configuration data.

  pydantic_core - MIT
      How VethuQ uses it: the engine behind pydantic.

  annotated-types - MIT
      How VethuQ uses it: type constraints used by pydantic.

  typing-inspection - MIT
      How VethuQ uses it: type checks used by pydantic.

  typing_extensions - PSF-2.0
      How VethuQ uses it: newer typing features for older Python versions.

  colorlog - MIT
      How VethuQ uses it: coloured log output from the OCR libraries.

  prettytable - BSD-3-Clause
      How VethuQ uses it: table output from the OCR libraries.

  future - MIT
      How VethuQ uses it: Python 2/3 compatibility used by a PaddlePaddle dependency.

  six - MIT
      How VethuQ uses it: Python 2/3 compatibility used by dependencies.


Downloading the OCR models (first use)

  requests - Apache-2.0
      How VethuQ uses it: HTTP requests when downloading model files.

  urllib3 - MIT
      How VethuQ uses it: HTTP connections used by requests.

  certifi - MPL-2.0
      How VethuQ uses it: trusted certificate list for secure downloads.

  idna - BSD-3-Clause
      How VethuQ uses it: international domain names in download addresses.

  truststore - MIT
      How VethuQ uses it: uses the operating system's certificate store for secure downloads.

  httpx - BSD-3-Clause
      How VethuQ uses it: HTTP client used by the model-download libraries.

  httpx2 - BSD-3-Clause
      How VethuQ uses it: HTTP client used by the model-download libraries.

  httpcore - BSD-3-Clause
      How VethuQ uses it: transport layer for httpx.

  httpcore2 - BSD-3-Clause
      How VethuQ uses it: transport layer for httpx2.

  h11 - MIT
      How VethuQ uses it: HTTP/1.1 protocol handling for httpx.

  anyio - MIT
      How VethuQ uses it: async I/O layer for httpx.

  huggingface_hub - Apache-2.0
      How VethuQ uses it: downloads models from the Hugging Face hub.

  hf-xet - Apache-2.0
      How VethuQ uses it: faster transfers for the Hugging Face hub.

  modelscope - Apache-2.0
      How VethuQ uses it: downloads models from ModelScope.

  modelscope-hub - Apache-2.0
      How VethuQ uses it: the ModelScope model hub client.

  aistudio_sdk - Apache-2.0
      How VethuQ uses it: downloads models from AI Studio.

  bce-python-sdk - Apache License 2.0
      How VethuQ uses it: downloads models from Baidu cloud storage.

  pycryptodome - BSD and public domain
      How VethuQ uses it: checksums and encryption used by the cloud SDKs.

  crc32c - LGPL-2.1 or later
      How VethuQ uses it: checksum calculation for downloaded files.

  cryptography - Apache-2.0 or BSD-3-Clause
      How VethuQ uses it: secure connections for downloads.

  cffi - MIT-0
      How VethuQ uses it: native bindings used by cryptography.

  pycparser - BSD-3-Clause
      How VethuQ uses it: C parsing used by cffi.

  tqdm - MPL-2.0 and MIT
      How VethuQ uses it: download progress bars.

  filelock - MIT
      How VethuQ uses it: keeps concurrent model downloads from clashing.

  fsspec - BSD-3-Clause
      How VethuQ uses it: file access used by the model-download libraries.

  chardet - 0BSD
      How VethuQ uses it: detects text encodings in downloaded files.

  python-dateutil - Apache-2.0 or BSD-3-Clause
      How VethuQ uses it: date handling in the model-download libraries.

  tzdata - Apache-2.0
      How VethuQ uses it: time zone data.


VethuQ application

  platformdirs - MIT
      How VethuQ uses it: finds the per-user folders where VethuQ keeps its data and settings.

  psutil - BSD-3-Clause
      How VethuQ uses it: starts, monitors and stops the background index worker.

  typer - MIT
      How VethuQ uses it: the command-line framework behind 'vethuq'.

  click - BSD-3-Clause
      How VethuQ uses it: command-line parsing used by typer.

  shellingham - ISC
      How VethuQ uses it: detects the shell for typer.

  annotated-doc - MIT
      How VethuQ uses it: documentation of command options used by typer.

  rich - MIT
      How VethuQ uses it: formatted tables, panels and colour in the command line.

  markdown-it-py - MIT
      How VethuQ uses it: text formatting used by rich.

  mdurl - MIT
      How VethuQ uses it: link handling used by markdown-it-py.

  Pygments - BSD-2-Clause
      How VethuQ uses it: syntax colouring used by rich.

  colorama - BSD-3-Clause
      How VethuQ uses it: terminal colours on Windows.

  wcwidth - MIT
      How VethuQ uses it: measures text width for terminal layout.

  packaging - Apache-2.0 or BSD-2-Clause
      How VethuQ uses it: reads and compares package versions.

  sv_ttk - MIT
      How VethuQ uses it: the Sun Valley theme of the desktop application.


Bundled runtime and build tool

  Python runtime - Python Software Foundation License
      How VethuQ uses it: the interpreter bundled with the desktop app.

  PyInstaller - GPL-2.0 with a special exception that allows its bootloader to be distributed with
      programs under any license
      How VethuQ uses it: packages the desktop app.


FILE TYPES (installed when selected)
------------------------------------


PDF

  PyMuPDF (pymupdf) - GNU AGPL-3.0, or a commercial license from Artifex
      How VethuQ uses it: reads PDF files and renders their pages for OCR. VethuQ uses it under
      the AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html).


PNG image

  No additional packages; uses OpenCV and NumPy from the core runtime.


JPEG image

  No additional packages; uses OpenCV and NumPy from the core runtime.
