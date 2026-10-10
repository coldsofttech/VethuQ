import re

import pytest

from vethuq._brand import _Brand, _Palette

_HEX = re.compile(r"^#[0-9A-F]{6}$")


def _luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    light, dark = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# (foreground token, background token): text pairings that must stay readable (WCAG AA, 4.5:1).
_TEXT_PAIRS = [
    ("text", "bg"),
    ("text", "surface"),
    ("text-muted", "bg"),
    ("text-muted", "surface"),
    ("primary", "bg"),
    ("primary", "surface"),
    ("on-primary", "primary"),
    ("on-highlight", "highlight"),
    ("accent", "bg"),
    ("success", "bg"),
    ("danger", "bg"),
]


class TestPalette:
    def test_both_schemes_define_the_same_tokens(self):
        schemes = _Palette.schemes()

        assert set(schemes) == set(_Palette.SCHEMES)
        assert set(schemes["light"]) == set(schemes["dark"])

    @pytest.mark.parametrize("scheme", _Palette.SCHEMES)
    def test_every_token_is_an_uppercase_hex_color(self, scheme):
        for token, value in _Palette.schemes()[scheme].items():
            assert _HEX.match(value), f"{scheme}.{token} = {value}"

    @pytest.mark.parametrize("scheme", _Palette.SCHEMES)
    @pytest.mark.parametrize(("foreground", "background"), _TEXT_PAIRS)
    def test_text_pairings_meet_wcag_aa(self, scheme, foreground, background):
        colors = _Palette.schemes()[scheme]

        assert _contrast(colors[foreground], colors[background]) >= 4.5

    def test_warning_text_is_readable_on_its_background_in_both_schemes(self):
        for scheme in _Palette.SCHEMES:
            colors = _Palette.schemes()[scheme]
            assert _contrast(colors["warning"], colors["warning-bg"]) >= 4.5

    def test_the_light_primary_matches_the_desktop_themes_accent(self):
        # sv_ttk draws the desktop UI with these accents; the palette is built around them.
        assert _Palette.get("primary", "light") == "#005FB8"
        assert _Palette.get("primary", "dark") == "#57C8FF"

    def test_get_returns_a_token_and_rejects_unknown_ones(self):
        assert _Palette.get("primary") == _Palette.get("primary", "light")
        with pytest.raises(KeyError):
            _Palette.get("not-a-token")

    def test_css_variables_cover_every_token_in_both_schemes(self):
        css = _Palette.css_variables()
        light, _, dark = css.partition("@media (prefers-color-scheme: dark)")

        for token, value in _Palette.schemes()["light"].items():
            assert f"--vq-{token}: {value};" in light
        for token, value in _Palette.schemes()["dark"].items():
            assert f"--vq-{token}: {value};" in dark


class TestBrand:
    def test_name_and_tagline(self):
        assert _Brand.NAME == "VethuQ"
        assert _Brand.TAGLINE == "Document intelligence and evidence infrastructure."
