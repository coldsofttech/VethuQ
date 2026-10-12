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
        for row in service.list("indexing"):
            assert row["value"] == row["default"], row["id"]
            assert type(row["value"]) is type(row["default"]), row["id"]
            assert row["is_default"] is True

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
