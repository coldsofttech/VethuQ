"""Static checks on the installer files.

Inno Setup and PyInstaller only run on a Windows build machine, so these read the scripts as
text to catch the mistakes that would only show up there: a `Check:` naming a function that is
not defined, a language that is chosen but never written down, a data folder the frozen app needs
but the spec leaves out.
"""

import json
import re
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "installer"
CORE = Path(__file__).resolve().parents[2] / "vethuq-core" / "src" / "vethuq_core"
ISS = (INSTALLER / "vethuq.iss").read_text(encoding="utf-8")
SPEC = (INSTALLER / "vethuq.spec").read_text(encoding="utf-8")


def _code_section() -> str:
    return ISS[ISS.index("[Code]") :]


def _routine(name: str) -> str:
    """The text of procedure/function `name` in [Code], up to the next top-level routine."""
    found = re.search(
        rf"^(?:procedure|function) {name}\b.*?(?=^(?:procedure|function) |\Z)",
        _code_section(),
        re.MULTILINE | re.DOTALL,
    )
    assert found is not None, name
    return found.group()


class TestInnoScript:
    def test_every_check_function_is_defined(self):
        used = set(re.findall(r"Check:\s*(\w+)", ISS))
        defined = set(re.findall(r"^function\s+(\w+)", _code_section(), re.MULTILINE))

        assert used, "expected [Files] entries with a Check"
        assert used <= defined, used - defined

    def test_the_fallback_font_is_copied_independently_of_the_program_files(self):
        entry = next(line for line in ISS.splitlines() if "assets\\fonts" in line)

        assert 'DestDir: "{app}\\fonts"' in entry
        assert "Check: TeluguFontNeeded" in entry
        assert "FilesNeeded" not in entry
        assert "Components: app" in entry

    def test_the_font_is_needed_only_for_telugu_without_a_native_font(self):
        needed = _routine("TeluguFontNeeded")

        assert "IsLanguageChosen('te')" in needed
        assert "not HasNativeTeluguFont" in needed

    @pytest.mark.parametrize("face", ["nirmala ui", "gautami ", "vani "])
    def test_the_native_fonts_it_looks_for(self, face):
        assert f"Pos('{face}', Name) = 1" in ISS

    def test_the_font_list_is_read_machine_wide_and_per_user(self):
        assert "RootHasTeluguFont(HKEY_LOCAL_MACHINE)" in ISS
        assert "RootHasTeluguFont(HKEY_CURRENT_USER)" in ISS

    def test_a_silent_install_can_name_the_languages(self):
        assert "{param:LANGS|}" in ISS
        assert "LanguageWasSelected" in ISS

    def test_the_selection_is_written_as_a_list_english_included(self):
        save = _routine("SaveLanguageSelection")

        assert "LanguagePage.Values[I] or LanguageDefault(I)" in save
        assert '{ "enabled": [' in save
        assert "SaveLanguageSelection;" in _code_section()

    def test_the_languages_page_is_a_checkbox_list_not_a_single_choice(self):
        page = _routine("InitLanguagePage")

        assert "CreateInputOptionPage(" in page
        assert "False, False" in page  # not a radio list
        assert "LanguagePage.CheckListBox.ItemEnabled[I] := False" in page  # English locked
        assert "'Select all'" in page and "'Unselect all'" in page

    def test_the_summary_lists_the_chosen_languages(self):
        assert "'Languages:'" in ISS

    def test_the_single_choice_language_code_is_gone(self):
        assert "LanguagePage.SelectedValueIndex" not in ISS
        assert "DefaultLanguageIndex" not in ISS

    def test_the_pages_keep_their_order(self):
        assert re.search(r"CreateInputOptionPage\(\s*OcrPage\.ID, 'Languages'", ISS)
        assert re.search(r"CreateInputOptionPage\(\s*LanguagePage\.ID, 'File types'", ISS)

    def test_the_generated_language_catalog_includes_telugu(self):
        catalog = json.loads((INSTALLER / "languages.json").read_text(encoding="utf-8"))
        include = (INSTALLER / "languages.iss").read_text(encoding="utf-8")

        assert [entry["id"] for entry in catalog["languages"]] == ["en", "te"]
        assert "const LanguageCount = 2;" in include
        assert include.isascii(), "Inno include files are not Unicode-safe"


class TestPyInstallerSpec:
    @pytest.mark.parametrize("kind", ["engines", "languages"])
    def test_the_ocr_manifests_are_shipped_as_files(self, kind):
        assert "OCR_MANIFEST_DATAS" in SPEC
        assert '"ocr" / kind / "manifests"' in SPEC or kind in SPEC
        assert (CORE / "ocr" / kind / "manifests").is_dir()

    def test_all_three_executables_get_them(self):
        assert SPEC.count("*OCR_MANIFEST_DATAS") == 3

    def test_all_three_know_the_language_markers(self):
        assert SPEC.count("*LANGUAGE_HIDDEN") == 3

    def test_the_markers_are_the_non_english_languages(self):
        stems = {p.stem for p in (CORE / "ocr" / "languages" / "manifests").glob("*.json")}

        assert stems == {"en", "te"}
        assert 'manifest.stem != "en"' in SPEC

    def test_the_fonts_are_not_bundled_the_installer_places_them(self):
        assert '"assets" / "brand"' in SPEC and '"assets" / "icons"' in SPEC
        assert 'str(UI_SRC / "assets"),' not in SPEC
        assert (
            "fonts" not in re.sub(r"#.*", "", SPEC).replace("assets/fonts", "").split("UI_SRC")[0]
        )


class TestLicenseSummary:
    def test_the_font_and_its_license_are_listed(self):
        text = (INSTALLER / "LICENSE.md").read_text(encoding="utf-8")

        assert "Noto Sans Telugu" in text
        assert "SIL Open Font License" in text
        assert "vethuq-lang-te" in text

    def test_the_rtf_the_installer_shows_matches(self):
        rtf = (INSTALLER / "LICENSE.rtf").read_text(encoding="ascii")

        assert "Noto Sans Telugu (font)" in rtf
        assert "SIL Open Font License 1.1" in rtf
