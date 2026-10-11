from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from vethuq._credits import _PageTooLarge, _Pricing, _Terms, milli

POLICY = Path(__file__).resolve().parents[4] / "policy" / "examples" / "v1"
A4 = (595.276, 841.89)


def pricing(**over) -> _Pricing:
    return _Pricing(_Terms(**over))


class TestSizeFactor:
    # The table in docs/credits.md, section 5.1 (A1 and A0 follow the formula: see the doc).
    @pytest.mark.parametrize(
        ("name", "size", "factor"),
        [
            ("A6", (297.64, 419.53), 0.25),
            ("A5", (419.53, 595.28), 0.5),
            ("Letter", (612, 792), 1.0),
            ("A4", A4, 1.0),
            ("Legal", (612, 1008), 1.25),
            ("A3", (841.89, 1190.55), 2.0),
            ("A2", (1190.55, 1683.78), 4.0),
            ("A1", (1683.78, 2383.94), 7.75),
            ("A0", (2383.94, 3370.39), 15.25),
        ],
    )
    def test_the_paper_sizes(self, name, size, factor):
        assert pricing().size_factor(*size) == factor, name

    def test_tiny_pages_cost_the_minimum(self):
        assert pricing().size_factor(50, 50) == 0.25

    def test_an_unknown_size_counts_as_a4(self):
        p = pricing()
        assert p.size_factor(None, None) == 1.0
        assert p.size_factor(0, 800) == 1.0
        assert p.size_factor(-1, 800) == 1.0

    def test_bigger_than_a0_is_refused(self):
        with pytest.raises(_PageTooLarge):
            pricing().size_factor(2400 * 1.2, 3400 * 1.2)

    def test_the_limits_come_from_the_rate_card(self):
        p = pricing(step=0.5, minimum=0.5, tolerance_percent=0, per_page_max=2)
        assert p.size_factor(*A4) == 1.0
        assert p.size_factor(300, 400) == 0.5
        with pytest.raises(_PageTooLarge):
            p.size_factor(841.89 * 1.2, 1190.55 * 1.2)

    @pytest.mark.parametrize(
        ("factor", "bucket"),
        [(0.25, "xs"), (0.5, "s"), (1.0, "m"), (1.25, "l"), (2.0, "l"), (2.25, "xl"), (15, "xl")],
    )
    def test_buckets(self, factor, bucket):
        assert _Pricing.bucket(factor) == bucket


class TestCost:
    def test_a_quick_pass_is_the_size_factor(self):
        p = pricing()
        assert p.cost_milli(1.0) == 1000
        assert p.cost_milli(2.0) == 2000
        assert p.cost_milli(0.25) == 250

    def test_an_additional_language_uses_its_own_rate(self):
        p = pricing(language_pass=0.5)
        assert p.cost_milli(2.0, additional_language=True) == 1000

    def test_the_multipliers_apply(self):
        assert pricing(cpu=2.0, fast=1.5).cost_milli(1.0) == 3000

    def test_a_part_of_a_page_costs_that_share_with_the_minimum(self):
        p = pricing()
        assert p.cost_milli(1.0, covered=0.5) == 500
        assert p.cost_milli(1.0, covered=0.01) == 250  # the minimum
        assert p.cost_milli(0.25, covered=0.01) == 250  # never more than the page
        assert p.cost_milli(1.0, covered=1.0) == 1000

    def test_a_blank_page_costs_the_minimum_only(self):
        p = pricing()
        assert p.blank_milli(1000) == 250
        assert p.blank_milli(250) == 250
        assert p.blank_milli(100) == 100


class TestTermsFromPolicy:
    def test_defaults_are_the_documented_numbers(self):
        t = _Terms.from_policy({})
        assert (t.local_daily, t.local_starter, t.grace_percent, t.grace_mode) == (
            500,
            2000,
            2,
            "free",
        )
        assert (t.bonus_percent, t.bonus_cap_percent, t.rotated_factor) == (10, 15, 0.8)

    def test_the_example_rate_card(self):
        raw = json.loads((POLICY / "with-rate-card.payload.json").read_text())
        t = _Terms.from_policy(raw, "1.0.0")
        assert t.rate_card_version == 3
        assert (t.local_daily, t.local_starter) == (500, 2000)
        assert (t.one_off_max, t.one_off_expiry_days, t.device_daily_ceiling) == (10000, 365, 2000)
        assert t.metrics_endpoint == "https://example.com/metrics"
        assert t.metrics_max_batch_bytes == 65536
        (promotion,) = t.promotions
        assert (promotion.id, promotion.percent, promotion.start) == (
            "launch-week",
            50,
            "2026-11-01",
        )

    def test_bad_values_fall_back(self):
        raw = {
            "rate_card": {"page_size": {"step": -1, "minimum": "x"}, "phases": {"quick": True}},
            "wallets": {"local": {"daily": "lots", "starter": -5}},
            "grace_percent": "x",
            "grace_mode": "weird",
            "metrics": {"enabled": "yes", "max_batch_bytes": 0},
        }
        t = _Terms.from_policy(raw)
        assert (t.step, t.minimum, t.quick) == (0.25, 0.25, 1.0)
        assert (t.local_daily, t.local_starter) == (500, 2000)
        assert (t.grace_percent, t.grace_mode) == (2, "free")
        assert (t.metrics_enabled, t.metrics_max_batch_bytes) == (True, 65536)

    def test_a_section_for_other_client_versions_is_ignored(self):
        raw = {"wallets": {"applies_to": {"client": {"min": "2.0.0"}}, "local": {"daily": 5}}}
        assert _Terms.from_policy(raw, "1.0.0").local_daily == 500
        assert _Terms.from_policy(raw, "2.1.0").local_daily == 5

    def test_the_whole_payloads_scope_applies_too(self):
        raw = {
            "applies_to": {"client": {"max": "0.9.0"}},
            "wallets": {"local": {"daily": 5}},
        }
        assert _Terms.from_policy(raw, "1.0.0").local_daily == 500
        assert _Terms.from_policy(raw, "0.5.0").local_daily == 5

    def test_a_round_trip(self):
        raw = json.loads((POLICY / "with-rate-card.payload.json").read_text())
        t = _Terms.from_policy(raw)
        assert _Terms.from_dict(json.loads(json.dumps(t.to_dict()))) == t

    def test_milli(self):
        assert milli(1.0005) == 1000 or milli(1.0005) == 1001
        assert milli(0.25) == 250


class TestPromotions:
    RAW = {
        "promotions": [
            {
                "id": "a",
                "name": "A",
                "start_date": "2026-11-01",
                "end_date": "2026-11-07",
                "uplift": {"local": {"percent": 50}},
            },
            {
                "id": "b",
                "name": "B",
                "start_date": "2026-11-05",
                "end_date": "2026-11-10",
                "uplift": {"local": {"absolute": 300}, "github": {"absolute": 5}},
                "min_client": "1.0.0",
            },
            {"id": "broken", "uplift": 5},
            {
                "id": "other-wallet",
                "name": "C",
                "start_date": "2026-11-01",
                "end_date": "2026-11-30",
                "uplift": {"github": {"absolute": 5}},
            },
        ]
    }

    def terms(self, version="1.0.0"):
        return _Terms.from_policy(self.RAW, version)

    def test_only_local_promotions_are_read(self):
        assert [p.id for p in self.terms().promotions] == ["a", "b"]

    def test_the_biggest_uplift_wins_they_do_not_stack(self):
        t = self.terms()
        promo, amount = t.best_promotion(date(2026, 11, 6), 500_000)
        assert (promo.id, amount) == ("b", 300_000)  # 300 beats 50% of 500 = 250
        promo, amount = t.best_promotion(date(2026, 11, 2), 500_000)
        assert (promo.id, amount) == ("a", 250_000)

    def test_outside_the_window_there_is_none(self):
        assert self.terms().best_promotion(date(2026, 10, 31), 500_000) is None
        assert self.terms().best_promotion(date(2026, 11, 11), 500_000) is None

    def test_the_uplift_is_capped(self):
        t = _Terms.from_policy({**self.RAW, "caps": {"promotion_uplift_percent": 20}}, "1.0.0")
        assert t.best_promotion(date(2026, 11, 6), 500_000)[1] == 100_000

    def test_a_promotion_for_a_newer_client_is_skipped(self):
        assert [p.id for p in self.terms("0.5.0").promotions] == ["a"]
