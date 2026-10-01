import pytest
from rich.style import Style
from vethuq_cli.theme import Theme
from vethuq_core.branding import Palette


class TestTheme:
    def test_colors_come_from_the_dark_palette(self):
        assert Theme.PRIMARY == Palette.get("primary", "dark")
        assert Theme.DANGER == Palette.get("danger", "dark")
        assert Theme.ACCENT == Palette.get("accent", "dark")

    @pytest.mark.parametrize(
        "style",
        [
            Theme.ERROR,
            Theme.OK,
            Theme.PAUSED,
            Theme.NOTICE,
            Theme.INFO,
            Theme.VALUE,
            Theme.LABEL,
            Theme.COMMAND,
            Theme.BRAND,
            f"bold {Theme.ON_HIGHLIGHT} on {Theme.PRIMARY}",
        ],
    )
    def test_every_style_is_a_valid_rich_style(self, style):
        assert Style.parse(style) is not None
