from __future__ import annotations

import pytest
from api_support import ORIGIN

from vethuq import VethuQ
from vethuq_api import allow_host, create_app
from vethuq_api.core import VethuQCore
from vethuq_api.settings import InvalidSettingError, SettingNotFoundError, SettingsService

HEADERS = {"Origin": ORIGIN}


@pytest.fixture
def vethuq(tmp_path):
    instance = VethuQ(tmp_path / "vethuq.db")
    yield instance
    instance.close()


@pytest.fixture
def service(vethuq):
    return SettingsService(lambda: vethuq)


def by_id(rows):
    return {row["id"]: row for row in rows}


class TestListing:
    def test_indexing_section_lists_the_index_and_ocr_settings(self, service):
        rows = by_id(service.list("indexing"))
        assert list(rows) == [
            "index.workers",
            "index.retry_attempts",
            "ocr.engine",
            "ocr.gpu",
            "index.stability_check_seconds",
            "index.stale_lock",
        ]

    def test_the_stated_defaults_are_the_cores_defaults(self, service):
        """The defaults are written in this module; this fails if the core's change."""
        for section in service.sections():
            for row in service.list(section):
                assert row["value"] == row["default"], row["id"]
                assert type(row["value"]) is type(row["default"]), row["id"]
                assert row["is_default"] is True, row["id"]

    def test_sections_in_the_order_the_screen_shows_them(self, service):
        assert service.sections() == [
            "indexing",
            "general",
            "sources",
            "tiers",
            "results",
            "system",
        ]

    def test_advanced_settings_are_marked(self, service):
        rows = by_id(service.list("indexing"))
        assert {key for key, row in rows.items() if row["advanced"]} == {
            "index.stability_check_seconds",
            "index.stale_lock",
        }

    def test_workers_offer_auto_zero_and_one_to_the_maximum(self, service):
        values = [o["value"] for o in by_id(service.list("indexing"))["index.workers"]["options"]]
        assert values[:3] == ["auto", 0, 1]
        assert values[-1] == 8

    def test_ocr_depths_beyond_the_installed_phases_are_unavailable_with_a_reason(self, service):
        options = {o["value"]: o for o in by_id(service.list("indexing"))["ocr.engine"]["options"]}
        assert options["quick"]["available"] is True
        for depth in ("moderate", "deep"):
            if not options[depth]["available"]:
                assert "add-on" in options[depth]["reason"]

    def test_unknown_section_is_not_found(self, service):
        with pytest.raises(SettingNotFoundError):
            service.list("nope")


class TestChanging:
    def test_a_change_is_saved_and_no_longer_the_default(self, service, vethuq):
        row = service.update("indexing", "index.workers", 4)
        assert row["value"] == 4
        assert row["is_default"] is False
        assert vethuq.settings.index.get_workers() == 4

    def test_each_kind_of_setting_can_be_changed_and_reset(self, service, vethuq):
        service.update("indexing", "index.retry_attempts", 0)
        service.update("indexing", "ocr.gpu", True)
        service.update("indexing", "index.stability_check_seconds", 2)
        service.update("indexing", "index.stale_lock", "disable")
        service.update("indexing", "index.workers", 0)
        assert vethuq.settings.index.get_retry_attempts() == 0
        assert vethuq.settings.ocr.get_gpu() is True
        assert vethuq.settings.index.get_stability_check_seconds() == 2.0
        assert vethuq.settings.index.get_stale_lock() == "disable"
        assert vethuq.settings.index.get_workers() == 0

        for row in service.list("indexing"):
            assert service.reset("indexing", row["id"])["is_default"] is True

    @pytest.mark.parametrize(
        ("setting", "value"),
        [
            ("index.workers", 99),
            ("index.workers", "many"),
            ("index.workers", True),
            ("index.workers", None),
            ("index.retry_attempts", -1),
            ("index.retry_attempts", 1.5),
            ("index.retry_attempts", "3"),
            ("index.retry_attempts", True),
            ("index.stability_check_seconds", -0.5),
            ("index.stability_check_seconds", "1"),
            ("index.stale_lock", "sometimes"),
            ("ocr.gpu", "yes"),
            ("ocr.gpu", 1),
            ("ocr.engine", "turbo"),
        ],
    )
    def test_a_bad_value_is_refused_and_nothing_changes(self, service, setting, value):
        before = by_id(service.list("indexing"))[setting]["value"]
        with pytest.raises(InvalidSettingError):
            service.update("indexing", setting, value)
        assert by_id(service.list("indexing"))[setting]["value"] == before

    def test_an_ocr_depth_whose_add_on_is_missing_is_refused(self, service):
        options = {o["value"]: o for o in by_id(service.list("indexing"))["ocr.engine"]["options"]}
        missing = [depth for depth, option in options.items() if not option["available"]]
        if not missing:
            pytest.skip("every OCR depth is installed here")
        with pytest.raises(InvalidSettingError, match="add-on|Needs"):
            service.update("indexing", "ocr.engine", missing[0])

    def test_unknown_setting_is_not_found(self, service):
        with pytest.raises(SettingNotFoundError):
            service.update("indexing", "index.nope", 1)
        with pytest.raises(SettingNotFoundError):
            service.reset("nope", "index.workers")


class TestOtherSections:
    def test_each_section_lists_its_settings(self, service):
        assert list(by_id(service.list("general"))) == [
            "languages.languages",
            "updates.check",
            "metrics.opt_in",
            "updates.skipped_version",
            "updates.snoozed_until",
        ]
        assert list(by_id(service.list("sources"))) == ["sources.removed_retention_minutes"]
        assert list(by_id(service.list("results"))) == ["confidence.bands"]
        assert list(by_id(service.list("system"))) == [
            "logs.level",
            "logs.retention_days",
            "database.integrity_check",
            "database.integrity_check_interval_minutes",
        ]
        assert list(by_id(service.list("tiers"))) == [
            "tiers.default",
            "tiers.phases",
            "tiers.min_size_factor",
            "tiers.max_job_pages",
            "tiers.max_job_megabytes",
            "tiers.wait_timeout_minutes",
        ]
        advanced = {r["id"] for r in service.list("tiers") if r["advanced"]}
        assert advanced == {
            "tiers.max_job_pages",
            "tiers.max_job_megabytes",
            "tiers.wait_timeout_minutes",
        }

    def test_values_are_saved_in_the_core_and_can_be_reset(self, service, vethuq):
        service.update("general", "metrics.opt_in", True)
        service.update("sources", "sources.removed_retention_minutes", 0)
        service.update("tiers", "tiers.phases", ["moderate", "deep"])
        service.update("tiers", "tiers.min_size_factor", 3)
        service.update("tiers", "tiers.max_job_pages", 50)
        service.update("tiers", "tiers.max_job_megabytes", 20)
        service.update("tiers", "tiers.wait_timeout_minutes", 5)
        service.update("results", "confidence.bands", [50, 60, 70])
        assert vethuq.settings.metrics.get_opt_in() is True
        assert vethuq.settings.sources.get_removed_retention_minutes() == 0
        assert vethuq.settings.tiers.get_phases() == ["moderate", "deep"]
        assert vethuq.settings.tiers.get_min_size_factor() == 3.0
        assert vethuq.settings.tiers.get_max_job_pages() == 50
        assert vethuq.settings.tiers.get_max_job_megabytes() == 20
        assert vethuq.settings.tiers.get_wait_timeout_minutes() == 5
        assert vethuq.settings.confidence.get_bands() == (50, 60, 70)

        for section in ("general", "sources", "tiers", "results"):
            for row in service.list(section):
                assert service.reset(section, row["id"])["is_default"] is True

    def test_the_languages_offered_are_the_cores_and_one_is_required(self, service, vethuq):
        row = by_id(service.list("general"))["languages.languages"]
        assert [o["value"] for o in row["options"]] == [
            language.id for language in vethuq.languages.list_all()
        ]
        assert row["min"] == 1
        with pytest.raises(InvalidSettingError, match="at least 1"):
            service.update("general", "languages.languages", [])

    def test_the_default_languages_follow_the_core(self, service, vethuq):
        row = by_id(service.list("general"))["languages.languages"]
        assert row["default"] == [lang.id for lang in vethuq.languages.list_all() if lang.default]

    def test_the_default_tier_is_chosen_from_the_available_ones(self, service, vethuq):
        row = by_id(service.list("tiers"))["tiers.default"]
        assert {o["value"] for o in row["options"]} >= {"local"}
        assert row["value"] == vethuq.tiers.current().id
        unavailable = [o for o in row["options"] if not o["available"]]
        for option in unavailable:
            with pytest.raises(InvalidSettingError):
                service.update("tiers", "tiers.default", option["value"])

    def test_bands_describe_their_three_fields(self, service):
        row = by_id(service.list("results"))["confidence.bands"]
        assert row["labels"] == ["Low from", "Medium from", "High from"]
        assert (row["min"], row["max"]) == (0, 100)

    @pytest.mark.parametrize(
        ("section", "setting", "value"),
        [
            ("general", "languages.languages", ["xx"]),
            ("general", "languages.languages", "en"),
            ("general", "languages.languages", ["en", "en"]),
            ("general", "metrics.opt_in", "on"),
            ("sources", "sources.removed_retention_minutes", -1),
            ("sources", "sources.removed_retention_minutes", 1.5),
            ("tiers", "tiers.phases", ["nope"]),
            ("tiers", "tiers.phases", "moderate"),
            ("tiers", "tiers.min_size_factor", -1),
            ("tiers", "tiers.min_size_factor", "big"),
            ("tiers", "tiers.max_job_pages", 0),
            ("tiers", "tiers.max_job_megabytes", 0),
            ("tiers", "tiers.wait_timeout_minutes", 0),
            ("tiers", "tiers.default", "mars"),
            ("results", "confidence.bands", [90, 80, 70]),
            ("results", "confidence.bands", [70, 80]),
            ("results", "confidence.bands", [70, 80, 101]),
            ("results", "confidence.bands", [70.5, 80, 90]),
            ("results", "confidence.bands", [True, 80, 90]),
            ("results", "confidence.bands", "70,80,90"),
        ],
    )
    def test_a_bad_value_is_refused_and_nothing_changes(self, service, section, setting, value):
        before = by_id(service.list(section))[setting]["value"]
        with pytest.raises(InvalidSettingError):
            service.update(section, setting, value)
        assert by_id(service.list(section))[setting]["value"] == before


class TestSystemAndUpdates:
    def test_choices_are_plain_values_not_enum_members(self, service):
        rows = by_id(service.list("system")) | by_id(service.list("general"))
        for key in ("logs.level", "updates.check", "database.integrity_check"):
            assert type(rows[key]["value"]) is str, key
        assert [o["value"] for o in rows["updates.check"]["options"]] == [
            "on",
            "notify-only",
            "off",
        ]
        assert [o["value"] for o in rows["logs.level"]["options"]] == [
            "debug",
            "info",
            "warning",
            "error",
        ]

    def test_values_reach_the_core_and_reset(self, service, vethuq):
        service.update("system", "logs.level", "warning")
        service.update("system", "logs.retention_days", 3)
        service.update("system", "database.integrity_check", "disable")
        service.update("system", "database.integrity_check_interval_minutes", 60)
        service.update("general", "updates.check", "off")
        assert vethuq.settings.logs.get_level().value == "warning"
        assert vethuq.settings.logs.get_retention_days() == 3
        assert vethuq.settings.database.get_integrity_check().value == "disable"
        assert vethuq.settings.database.get_integrity_check_interval_minutes() == 60
        assert vethuq.settings.updates.get_check().value == "off"
        for section, key in [
            ("system", "logs.level"),
            ("system", "logs.retention_days"),
            ("system", "database.integrity_check"),
            ("system", "database.integrity_check_interval_minutes"),
            ("general", "updates.check"),
        ]:
            assert service.reset(section, key)["is_default"] is True

    @pytest.mark.parametrize(
        ("section", "setting", "value"),
        [
            ("system", "logs.level", "verbose"),
            ("system", "logs.level", "INFO"),
            ("system", "logs.retention_days", 0),
            ("system", "logs.retention_days", 2.5),
            ("system", "database.integrity_check", "sometimes"),
            ("system", "database.integrity_check_interval_minutes", 0),
            ("general", "updates.check", "yes"),
            ("general", "updates.check", True),
        ],
    )
    def test_a_bad_value_is_refused(self, service, section, setting, value):
        with pytest.raises(InvalidSettingError):
            service.update(section, setting, value)

    def test_the_skipped_version_and_snooze_are_shown_read_only_and_can_be_cleared(
        self, service, vethuq
    ):
        rows = by_id(service.list("general"))
        for key in ("updates.skipped_version", "updates.snoozed_until"):
            assert rows[key]["readonly"] is True
            assert rows[key]["type"] == "text"
            assert rows[key]["value"] is None
            assert rows[key]["advanced"] is True

        vethuq.settings.updates.skip_version("9.9.9")
        vethuq.settings.updates.snooze(2)
        rows = by_id(service.list("general"))
        assert rows["updates.skipped_version"]["value"] == "9.9.9"
        assert rows["updates.skipped_version"]["is_default"] is False
        assert "T" in rows["updates.snoozed_until"]["value"]  # an ISO timestamp

        with pytest.raises(InvalidSettingError, match="cannot be changed"):
            service.update("general", "updates.skipped_version", "1.0")

        assert service.reset("general", "updates.skipped_version")["value"] is None
        assert service.reset("general", "updates.snoozed_until")["value"] is None

    def test_the_update_check_says_when_the_environment_overrides_it(self, service, monkeypatch):
        monkeypatch.delenv("VETHUQ_UPDATE_CHECK", raising=False)
        assert by_id(service.list("general"))["updates.check"]["note"] == ""
        monkeypatch.setenv("VETHUQ_UPDATE_CHECK", "off")
        note = by_id(service.list("general"))["updates.check"]["note"]
        assert "VETHUQ_UPDATE_CHECK" in note


class TestHttp:
    @pytest.fixture
    def http(self, web_dist, tmp_path):
        app = create_app(
            bootstrap_token="t", web_dist=web_dist, core=VethuQCore(tmp_path / "vethuq.db")
        )
        allow_host(app, "127.0.0.1:5000")
        client = app.test_client()
        client.get("/?t=t", base_url=ORIGIN)
        return client

    def test_list_change_and_reset_over_http(self, http):
        listing = http.get("/api/settings/indexing", base_url=ORIGIN).get_json()
        assert listing["section"] == "indexing"
        assert len(listing["settings"]) == 6

        changed = http.put(
            "/api/settings/indexing/index.workers",
            json={"value": 3},
            base_url=ORIGIN,
            headers=HEADERS,
        )
        assert changed.status_code == 200
        assert changed.get_json()["value"] == 3

        reset = http.delete(
            "/api/settings/indexing/index.workers", base_url=ORIGIN, headers=HEADERS
        )
        assert reset.get_json()["value"] == "auto"

    def test_an_invalid_value_is_a_422_with_the_reason(self, http):
        response = http.put(
            "/api/settings/indexing/index.retry_attempts",
            json={"value": -2},
            base_url=ORIGIN,
            headers=HEADERS,
        )
        assert response.status_code == 422
        assert "0 or more" in response.get_json()["error"]

    def test_a_missing_value_is_a_422(self, http):
        response = http.put(
            "/api/settings/indexing/ocr.gpu", json={}, base_url=ORIGIN, headers=HEADERS
        )
        assert response.status_code == 422

    def test_a_read_only_setting_cannot_be_written_over_http(self, http):
        response = http.put(
            "/api/settings/general/updates.skipped_version",
            json={"value": "1.0"},
            base_url=ORIGIN,
            headers=HEADERS,
        )
        assert response.status_code == 422

    def test_unknown_things_are_404(self, http):
        assert http.get("/api/settings/nope", base_url=ORIGIN).status_code == 404
        response = http.put(
            "/api/settings/indexing/nope", json={"value": 1}, base_url=ORIGIN, headers=HEADERS
        )
        assert response.status_code == 404

    def test_changing_needs_the_app_origin_and_a_session(self, http, client):
        no_origin = http.put(
            "/api/settings/indexing/ocr.gpu", json={"value": True}, base_url=ORIGIN
        )
        assert no_origin.status_code == 403
        anonymous = client.put(
            "/api/settings/indexing/ocr.gpu",
            json={"value": True},
            base_url=ORIGIN,
            headers=HEADERS,
        )
        assert anonymous.status_code == 401
