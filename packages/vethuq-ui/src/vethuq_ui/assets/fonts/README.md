# Fallback fonts

Noto Sans Telugu 2.005 (hinted TrueType), from the Noto project:
https://github.com/notofonts/telugu (built files: https://github.com/notofonts/notofonts.github.io,
`fonts/NotoSansTelugu/hinted/ttf`). Licensed under the SIL Open Font License 1.1, which is `OFL.txt`
here and must stay with the font files wherever they are distributed.

| File | SHA-256 |
| --- | --- |
| `NotoSansTelugu-Regular.ttf` | `b274780b69d1d23fe84b55e809a152cb2ac5306d33864b1f87622f6971871aae` |
| `NotoSansTelugu-Bold.ttf` | `ec98c4f82abfe52ebe00be298d39c469deb86cf027929987759ba1eab361fbb4` |
| `OFL.txt` | `58895a85166c3cecf04ed4db39dce60a6aa39dbb3c7ff36b917fb8650f2ddbce` |

What they are for: the Windows installer copies this folder to `{app}\fonts` only when Telugu is chosen
and Windows has no Telugu font of its own (Nirmala UI on Windows 10 and 11), and the desktop app loads
the files for its own process only (`vethuq_ui/fonts.py`, `AddFontResourceEx` with `FR_PRIVATE`). They are
not part of the PyInstaller bundle (see `installer/vethuq.spec`) and are never installed into Windows.

The fonts cover Telugu (100 of the block's 128 code points, including the joiners) but not Latin
letters, so they are a last resort for Telugu text, not a UI font.

To update: replace the files, update the hashes above (a test checks them), and keep `OFL.txt` current.
