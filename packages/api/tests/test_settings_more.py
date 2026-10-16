"""Search, data location, add-on settings and the support report."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from api_support import ORIGIN

from vethuq import VethuQ
from vethuq_addon_api import CliGroup, CliSetting
from vethuq_api import allow_host, create_app
from vethuq_api.core import VethuQCore
from vethuq_api.settings import InvalidSettingError, SettingNotFoundError, SettingsService
from vethuq_api.support import build_report

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


class TestSearch:
    def test_fixed_settings_come_first_then_what_is_installed(self, service):
        rows = service.list("search")
        ids = [row["id"] for row in rows]
        assert ids[:3] == [
            "search.engine",
            "search.snippet_context_chars",
            "search.export_format",
        ]
        assert [row["group"] for row in rows[:3]] == ["Searching"] * 3
        assert all(i.startswith(("search.normalize.", "search.option.")) for i in ids[3:])

    def test_normalizers_form_one_group_with_automatic_first(self, service, vethuq):
        rows = [r for r in service.list("search") if r["id"].startswith("search.normalize.")]
        assert {r["id"].split(".")[-1] for r in rows} == {n.id for n in vethuq.search.normalizers()}
        for row in rows:
            assert row["group"] == "How text is matched"
            assert row["options"][0]["value"] == "auto"
            assert row["value"] == "auto"

    def test_each_engine_with_options_has_its_own_group(self, service, vethuq):
        rows = [r for r in service.list("search") if r["id"].startswith("search.option.")]
        engines = {e.id: e for e in vethuq.search.engines() if e.options}
        assert {r["id"].split(".")[2] for r in rows} == set(engines)
        for row in rows:
            engine = engines[row["id"].split(".")[2]]
            assert row["group"] == f"{engine.label} engine"

    def test_the_default_engine_offers_all_hybrid_and_each_engine(self, service, vethuq):
        row = by_id(service.list("search"))["search.engine"]
        values = [o["value"] for o in row["options"]]
        assert values[:2] == ["all", "hybrid"]
        assert set(values[2:]) == {e.id for e in vethuq.search.engines()}

    def test_values_are_saved_in_the_core_and_reset(self, service, vethuq):
        service.update("search", "search.engine", "like")
        service.update("search", "search.snippet_context_chars", 200)
        service.update("search", "search.export_format", "html")
        assert vethuq.settings.search.get_engine() == "like"
        assert vethuq.settings.search.get_snippet_context_chars() == 200
        assert vethuq.settings.search.get_export_format() == "html"
        for row in service.list("search"):
            if row["is_default"] is False:
                assert service.reset("search", row["id"])["is_default"] is True

    def test_a_normalizer_level_is_saved(self, service, vethuq):
        service.update("search", "search.normalize.case", "ignore")
        assert vethuq.settings.search.get_case() == "ignore"
        assert by_id(service.list("search"))["search.normalize.case"]["is_default"] is False
        assert service.reset("search", "search.normalize.case")["value"] == "auto"

    def test_an_engine_option_is_saved_with_its_kind(self, service, vethuq):
        rows = by_id(service.list("search"))
        if "search.option.semantic.limit" not in rows:
            pytest.skip("the semantic engine is not installed")
        assert rows["search.option.semantic.limit"]["type"] == "integer"
        service.update("search", "search.option.semantic.limit", 10)
        assert vethuq.settings.search.get_option("semantic", "limit") == "10"
        assert by_id(service.list("search"))["search.option.semantic.limit"]["value"] == 10
        service.reset("search", "search.option.semantic.limit")
        assert vethuq.settings.search.get_option("semantic", "limit") == "25"

    @pytest.mark.parametrize(
        ("setting", "value"),
        [
            ("search.engine", "nope"),
            ("search.snippet_context_chars", -1),
            ("search.snippet_context_chars", 2001),
            ("search.snippet_context_chars", 1.5),
            ("search.export_format", "pdf"),
            ("search.normalize.case", "sometimes"),
            ("search.normalize.case", 1),
        ],
    )
    def test_a_bad_value_is_refused(self, service, setting, value):
        with pytest.raises(InvalidSettingError):
            service.update("search", setting, value)

    def test_an_unavailable_engine_cannot_be_the_default(self, service):
        row = by_id(service.list("search"))["search.engine"]
        for option in row["options"]:
            if not option["available"]:
                with pytest.raises(InvalidSettingError):
                    service.update("search", "search.engine", option["value"])

    def test_an_unknown_option_is_not_found(self, service):
        with pytest.raises(SettingNotFoundError):
            service.update("search", "search.option.nope.nothing", "x")


class TestLocations:
    def test_the_data_and_backups_folders_are_paths_in_the_general_section(self, service):
        rows = by_id(service.list("general"))
        for key in ("location.data", "location.backups"):
            assert rows[key]["type"] == "path"
            assert rows[key]["group"] == "Data"
            assert rows[key]["is_default"] is True
        assert rows["location.data"]["can_move"] is True
        assert rows["location.backups"]["can_move"] is False

    def test_a_new_data_folder_is_saved_and_can_be_reset(self, service, tmp_path):
        target = tmp_path / "elsewhere"
        row = service.update("general", "location.data", str(target), {"move": False})
        assert row["value"] == str(target.resolve())
        assert row["is_default"] is False
        row = service.reset("general", "location.data", {"move": False})
        assert row["is_default"] is True

    def test_resetting_with_the_data_moves_it_back_and_forgets_the_saved_folder(
        self, service, tmp_path
    ):
        """`Paths.reset_location(move=True)` alone would leave the data in the custom folder."""
        from vethuq import Paths

        custom = tmp_path / "custom"
        service.update("general", "location.data", str(custom), {"move": False})
        (custom / "db").mkdir(parents=True)
        (custom / "db" / "marker.txt").write_text("my data")

        row = service.reset("general", "location.data", {"move": True})
        assert row["is_default"] is True
        assert Paths.location_source() == "default"
        assert (Paths.data_root() / "db" / "marker.txt").read_text() == "my data"
        assert not (custom / "db").exists()

    def test_the_default_data_folder_stays_the_platform_one_after_a_move(self, service, tmp_path):
        before = by_id(service.list("general"))["location.data"]["default"]
        service.update("general", "location.data", str(tmp_path / "custom"), {"move": False})
        assert by_id(service.list("general"))["location.data"]["default"] == before

    def test_the_client_is_released_after_the_data_moves(self, vethuq, tmp_path):
        released = []
        service = SettingsService(lambda: vethuq, lambda: released.append(True))
        service.update("general", "location.data", str(tmp_path / "moved"), {"move": False})
        assert released == [True]

    def test_the_backups_folder_is_saved_and_can_be_reset(self, service, tmp_path):
        target = tmp_path / "backups-here"
        row = service.update("general", "location.backups", str(target))
        assert row["value"] == str(target.resolve())
        assert service.reset("general", "location.backups")["is_default"] is True

    def test_a_folder_that_cannot_be_used_is_refused_with_the_reason(self, service, tmp_path):
        blocker = tmp_path / "a-file"
        blocker.write_text("x")
        with pytest.raises(InvalidSettingError):
            service.update("general", "location.backups", str(blocker / "inside"))

    def test_the_environment_locks_the_data_folder(self, service, monkeypatch, tmp_path):
        monkeypatch.setenv("VETHUQ_HOME", str(tmp_path / "from-env"))
        row = by_id(service.list("general"))["location.data"]
        assert "VETHUQ_HOME" in row["locked"]
        with pytest.raises(InvalidSettingError, match="VETHUQ_HOME"):
            service.update("general", "location.data", str(tmp_path / "x"))
        with pytest.raises(InvalidSettingError, match="VETHUQ_HOME"):
            service.reset("general", "location.data")

    def test_the_data_folder_does_not_move_while_indexing_runs(self, tmp_path):
        busy = SimpleNamespace(
            index=SimpleNamespace(status=lambda: SimpleNamespace(active=True)),
            close=lambda: pytest.fail("the database must stay open"),
        )
        service = SettingsService(lambda: busy)
        with pytest.raises(InvalidSettingError, match="Indexing is running"):
            service.update("general", "location.data", str(tmp_path / "x"))

    @pytest.mark.parametrize("options", [{"move": "yes"}, {"other": True}])
    def test_only_a_true_or_false_move_option_is_accepted(self, service, tmp_path, options):
        with pytest.raises(InvalidSettingError):
            service.update("general", "location.data", str(tmp_path / "x"), options)

    def test_other_settings_take_no_options(self, service):
        with pytest.raises(InvalidSettingError, match="no options"):
            service.update("general", "metrics.opt_in", True, {"move": True})

    @pytest.mark.parametrize("value", ["", "   ", 5, None])
    def test_a_folder_needs_text(self, service, value):
        with pytest.raises(InvalidSettingError):
            service.update("general", "location.backups", value)

    def test_the_stated_backups_default_is_next_to_the_database(self, service):
        from vethuq import Paths

        row = by_id(service.list("general"))["location.backups"]
        assert row["default"] == str(Paths.backups_dir())


class FakeAddons:
    """A client whose `addons.cli()` gives the settings of two add-ons."""

    def __init__(self):
        self.values = {
            "enabled": "true",
            "interval-minutes": "720",
            "ratio": "0.5",
            "mode": "fast",
            "note": "hello",
            "cpu-percent": "80",
        }
        self.resets: list[str] = []
        self.addons = SimpleNamespace(cli=self._cli)

    def _setting(self, name, help_, *, choices=(), reset=True, fail=None):
        def get(client):
            if fail:
                raise RuntimeError(fail)
            return client.values[name]

        def set_(client, value):
            if value == "bad":
                raise ValueError("That value is not allowed.")
            client.values[name] = value

        return CliSetting(
            name,
            help_,
            get,
            set_,
            (lambda client: client.resets.append(name)) if reset else None,
            choices=choices,
        )

    def _cli(self):
        backup = CliGroup(
            "backup",
            "Database backups (licensed).",
            settings=(
                self._setting("enabled", "Automatic backups: true or false."),
                self._setting("interval-minutes", "Minutes between automatic backups."),
                self._setting("ratio", "A ratio."),
                self._setting("mode", "How fast.", choices=("fast", "safe")),
                self._setting("note", "A note.", reset=False),
            ),
        )
        autoscale = CliGroup(
            "autoscale",
            "Adaptive workers.",
            settings=(
                self._setting("cpu-percent", "The CPU load to stay under (20 to 100)."),
                self._setting("secret", "Needs a licence.", fail="Not licensed."),
            ),
        )
        return [("backup", backup), ("autoscale", autoscale)]


class TestAddons:
    @pytest.fixture
    def fake(self):
        return FakeAddons()

    @pytest.fixture
    def addons(self, fake):
        return SettingsService(lambda: fake)

    def test_an_add_on_that_is_not_running_gets_a_read_only_row_with_the_reason(self, fake):
        fake.addons = SimpleNamespace(
            cli=fake._cli,
            list=lambda: [
                SimpleNamespace(
                    id="docx",
                    name="vethuq-addon-docx",
                    status=SimpleNamespace(value="incompatible"),
                    detail="built for Windows; VethuQ is running on Linux",
                ),
                SimpleNamespace(
                    id="backup", name="b", status=SimpleNamespace(value="loaded"), detail=""
                ),
            ],
        )
        row = by_id(SettingsService(lambda: fake).list("addons"))["docx.status"]
        assert row["value"] == "Not running (incompatible)"
        assert row["note"] == "built for Windows; VethuQ is running on Linux"
        assert row["group"] == "vethuq-addon-docx" and not row["resettable"]
        assert "backup.status" not in by_id(SettingsService(lambda: fake).list("addons"))

    def test_without_add_on_settings_the_section_is_empty(self, service):
        assert service.list("addons") == []

    def test_each_add_on_is_a_group_and_each_setting_is_listed(self, addons):
        rows = addons.list("addons")
        assert [r["id"] for r in rows] == [
            "backup.enabled",
            "backup.interval-minutes",
            "backup.ratio",
            "backup.mode",
            "backup.note",
            "autoscale.cpu-percent",
            "autoscale.secret",
        ]
        assert {r["group"] for r in rows if r["id"].startswith("backup")} == {
            "Database backups (licensed)"
        }
        assert {r["group"] for r in rows if r["id"].startswith("autoscale")} == {"Adaptive workers"}

    def test_the_kind_of_control_follows_the_value(self, addons):
        rows = by_id(addons.list("addons"))
        assert rows["backup.enabled"]["type"] == "boolean"
        assert rows["backup.enabled"]["value"] is True
        assert rows["backup.interval-minutes"]["type"] == "integer"
        assert rows["backup.interval-minutes"]["value"] == 720
        assert rows["backup.interval-minutes"]["unit"] == "minutes"
        assert rows["backup.ratio"]["type"] == "number"
        assert rows["backup.mode"]["type"] == "choice"
        assert [o["value"] for o in rows["backup.mode"]["options"]] == ["fast", "safe"]
        assert rows["backup.note"]["type"] == "text"
        assert rows["backup.note"]["readonly"] is False

    def test_a_range_in_the_help_becomes_the_limits(self, addons):
        row = by_id(addons.list("addons"))["autoscale.cpu-percent"]
        assert (row["min"], row["max"]) == (20, 100)

    def test_a_setting_without_a_reset_cannot_be_reset(self, addons):
        rows = by_id(addons.list("addons"))
        assert rows["backup.note"]["resettable"] is False
        assert rows["backup.enabled"]["resettable"] is True
        with pytest.raises(InvalidSettingError, match="nothing to reset"):
            addons.reset("addons", "backup.note")

    def test_values_are_written_to_the_add_on_as_text(self, addons, fake):
        addons.update("addons", "backup.enabled", False)
        addons.update("addons", "backup.interval-minutes", 60)
        addons.update("addons", "backup.mode", "safe")
        addons.update("addons", "backup.note", "changed")
        addons.update("addons", "autoscale.cpu-percent", 50)
        assert fake.values["enabled"] == "false"
        assert fake.values["interval-minutes"] == "60"
        assert fake.values["mode"] == "safe"
        assert fake.values["note"] == "changed"
        assert fake.values["cpu-percent"] == "50"

    def test_reset_calls_the_add_on(self, addons, fake):
        addons.reset("addons", "backup.enabled")
        assert fake.resets == ["enabled"]

    def test_what_the_add_on_refuses_is_shown_as_the_reason(self, addons):
        with pytest.raises(InvalidSettingError, match="not allowed"):
            addons.update("addons", "backup.note", "bad")

    def test_a_value_outside_the_limits_is_refused_before_the_add_on(self, addons, fake):
        with pytest.raises(InvalidSettingError):
            addons.update("addons", "autoscale.cpu-percent", 10)
        assert fake.values["cpu-percent"] == "80"

    def test_a_setting_that_cannot_be_read_is_shown_with_why(self, addons):
        row = by_id(addons.list("addons"))["autoscale.secret"]
        assert row["readonly"] is True
        assert "Not licensed." in row["note"]
        with pytest.raises(InvalidSettingError, match="cannot be changed"):
            addons.update("addons", "autoscale.secret", "x")


class TestSupportReport:
    ABOUT = {"vethuq": "1.2.3", "python": "3.12.0", "platform": "Windows-11", "db_schema": 1}
    CATALOG = {
        "add_ons": [
            {"id": "csv", "name": "vethuq-addon-csv", "version": "0.1.0", "status": "loaded"}
        ],
        "file_types": [
            {"label": "CSV", "extensions": [".csv"], "available": True, "reason": ""},
            {"label": "PDF", "extensions": [".pdf"], "available": False, "reason": "no engine"},
        ],
        "search_engines": [{"label": "Exact", "available": True, "reason": ""}],
        "languages": [{"label": "English", "enabled": True, "available": True, "reason": ""}],
        "ocr_engines": [
            {"label": "PaddleOCR", "profiles": ["mobile"], "available": True, "reason": ""}
        ],
    }

    def report(self, changed=()):
        return build_report(
            about=self.ABOUT, catalog=self.CATALOG, changed=list(changed), data_location="default"
        )

    def test_it_says_what_is_installed(self):
        text = self.report()
        assert "- VethuQ: 1.2.3" in text
        assert "- Platform: Windows-11" in text
        assert "### Add-ons (1)" in text
        assert "| vethuq-addon-csv | 0.1.0 | loaded |" in text
        assert "| PDF | .pdf | unavailable (no engine) |" in text
        assert "| PaddleOCR | mobile | available |" in text

    def test_it_lists_the_settings_that_were_changed(self):
        text = self.report(
            [
                {"id": "index.workers", "label": "Files indexed at once", "value": 4},
                {"id": "ocr.gpu", "label": "Use the graphics card", "value": True},
                {"id": "languages.languages", "label": "Languages", "value": ["en", "te"]},
            ]
        )
        assert "- Files indexed at once (`index.workers`): 4" in text
        assert "(`ocr.gpu`): on" in text
        assert "(`languages.languages`): en, te" in text

    def test_with_nothing_changed_it_says_so(self):
        assert "_None._" in self.report().split("Settings changed")[1]

    def test_pipes_in_a_name_do_not_break_the_table(self):
        catalog = {**self.CATALOG, "add_ons": [{"name": "a|b", "version": "1", "status": "x"}]}
        text = build_report(about=self.ABOUT, catalog=catalog, changed=[], data_location="env")
        assert "a\\|b" in text


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

    def test_the_support_report_is_plain_text_without_folders(self, http, tmp_path):
        response = http.get("/api/support-info", base_url=ORIGIN)
        assert response.status_code == 200
        assert response.mimetype == "text/plain"
        text = response.get_data(as_text=True)
        assert text.startswith("## VethuQ support information")
        assert "### Add-ons" in text
        assert "- Data folder: default" in text
        assert str(tmp_path) not in text

    def test_the_report_lists_settings_that_were_changed(self, http):
        http.put(
            "/api/settings/indexing/index.workers",
            json={"value": 4},
            base_url=ORIGIN,
            headers=HEADERS,
        )
        text = http.get("/api/support-info", base_url=ORIGIN).get_data(as_text=True)
        assert "(`index.workers`): 4" in text

    def test_the_report_needs_a_session(self, web_dist, tmp_path):
        app = create_app(bootstrap_token="t", web_dist=web_dist)
        allow_host(app, "127.0.0.1:5000")
        assert app.test_client().get("/api/support-info", base_url=ORIGIN).status_code == 401

    def test_the_addons_section_is_listed_over_http(self, http):
        body = http.get("/api/settings/addons", base_url=ORIGIN).get_json()
        assert body == {"section": "addons", "settings": []}
