"""The image variants, and which one a job needs."""

from __future__ import annotations

import pytest

from vethuq_worker import variants
from vethuq_worker.variants import CORE_DEPENDENCIES, LANGUAGES, VARIANTS, choose, get, tag


class TestTheTable:
    def test_the_variants_are_the_ones_asked_for_lightest_first(self):
        by_rank = [v.name for v in sorted(VARIANTS.values(), key=lambda v: v.rank)]

        assert sorted(by_rank) == sorted(
            [
                "slim",
                "office",
                "web",
                "developer",
                "open-office",
                "deep-scan",
                "email",
                "image",
                "full",
            ]
        )
        assert by_rank[0] == "slim" and by_rank[-1] == "full"
        assert len({v.rank for v in VARIANTS.values()}) == len(VARIANTS)

    def test_every_variant_has_every_language(self):
        for variant in VARIANTS.values():
            assert set(LANGUAGES) <= set(variant.addons), variant.name

    def test_no_variant_lists_an_add_on_twice(self):
        for variant in VARIANTS.values():
            assert len(variant.addons) == len(set(variant.addons)), variant.name

    def test_the_quick_phase_is_everywhere_and_the_others_only_where_their_add_ons_are(self):
        for variant in VARIANTS.values():
            assert "quick" in variant.phases
            for phase in ("moderate", "deep"):
                has = f"vethuq-addon-ocr-{phase}" in variant.addons
                assert (phase in variant.phases) == has, (variant.name, phase)

    def test_each_bundle_variant_is_slim_and_that_bundles_add_ons(self):
        slim = set(get("slim").addons)
        for name in ("office", "web", "developer", "open-office", "email", "image", "deep-scan"):
            assert slim < set(get(name).addons)

    def test_full_has_everything_any_variant_has(self):
        full = set(get("full").addons)
        for variant in VARIANTS.values():
            assert set(variant.addons) <= full, variant.name

    def test_the_build_gets_a_wheel_for_everything(self):
        needed = set(variants.everything())

        assert set(CORE_DEPENDENCIES) <= needed
        assert set(get("full").addons) <= needed

    def test_an_unknown_variant_is_an_error(self):
        with pytest.raises(ValueError, match="no worker image variant"):
            get("tiny")

    def test_a_tag_is_the_version_and_the_variant(self):
        assert tag("0.2.0", "slim") == "0.2.0-slim"


class TestChoosing:
    def test_a_quick_job_needs_only_slim(self):
        assert choose(["quick"]) == "slim" and choose() == "slim" and choose([]) == "slim"

    @pytest.mark.parametrize("phase", ["moderate", "deep"])
    def test_a_deeper_phase_needs_deep_scan(self, phase):
        assert choose(["quick", phase]) == "deep-scan"

    def test_add_ons_that_come_with_vethuq_never_need_more_than_slim(self):
        assert choose(["quick"], ["pdf", "csv", "vethuq-addon-markdown"]) == "slim"

    @pytest.mark.parametrize(
        ("addon", "variant"),
        [
            ("eml", "email"),
            ("odt", "open-office"),
            ("heic", "image"),
            ("html", "web"),
            ("py", "developer"),
            ("docx", "office"),
        ],
    )
    def test_an_add_on_picks_the_lightest_variant_that_has_it(self, addon, variant):
        assert choose(["quick"], [addon]) == variant

    def test_what_no_single_bundle_covers_takes_full(self):
        assert choose(["quick"], ["docx", "heic"]) == "full"
        assert choose(["quick"], ["parquet"]) == "full"
        assert choose(["moderate"], ["docx"]) == "full"

    def test_something_unknown_never_raises_and_takes_full(self):
        assert choose(["slow-motion"]) == "full"
        assert choose(["quick"], ["no-such-addon"]) == "full"


class TestTheBuildListing:
    def test_a_variants_add_ons_are_printed_one_per_line(self, capsys):
        assert variants.main(["--list", "email"]) == 0

        lines = capsys.readouterr().out.split()
        assert "vethuq-addon-eml" in lines and "vethuq-addon-telugu" in lines

    def test_the_names_come_lightest_first(self, capsys):
        variants.main(["--names"])

        assert capsys.readouterr().out.split()[0] == "slim"

    def test_all_add_ons(self, capsys):
        variants.main(["--all-addons"])

        assert "vethuq-addon-parquet" in capsys.readouterr().out

    def test_an_unknown_name_is_refused(self, capsys):
        assert variants.main(["--list", "tiny"]) == 2
        assert "no worker image variant" in capsys.readouterr().err

    def test_the_extra_add_ons_leave_out_what_slim_has(self, capsys):
        variants.main(["--extra", "office"])
        extra = capsys.readouterr().out.split()

        assert "vethuq-addon-docx" in extra and "vethuq-addon-telugu" not in extra
        assert variants.main(["--extra", "slim"]) == 0
        assert capsys.readouterr().out.strip() == ""

    def test_the_file_runs_by_itself_with_only_the_standard_library(self):
        import subprocess
        import sys

        done = subprocess.run(
            [sys.executable, "-I", variants.__file__, "--names"],
            capture_output=True,
            text=True,
            check=True,
        )

        assert done.stdout.split()[0] == "slim"
