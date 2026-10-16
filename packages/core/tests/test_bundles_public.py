"""`VethuQ().bundles`: the bundles of add-ons, what is installed of each, and turning them off."""

from __future__ import annotations

import pytest

from tests.test_catalog_public import client, info, installed, load, served, trusted  # noqa: F401

pytestmark = pytest.mark.basic


class TestReading:
    def test_list_and_get_are_the_catalogs_bundles(self, client, served):  # noqa: F811
        load(client, served)

        assert [b.id for b in client.bundles.list("es")] == ["office"]
        assert client.bundles.get("office").addons == ("docx",)
        assert client.bundles.get("nope") is None

    def test_a_bundle_is_installed_when_every_add_on_is(self, client, served, monkeypatch):  # noqa: F811
        load(client, served)
        assert client.bundles.is_installed("office") is False

        installed(client, monkeypatch, info("docx"))

        assert client.bundles.is_installed("office") is True
        assert client.bundles.is_installed("nope") is False


class TestSetEnabled:
    def test_turns_the_installed_add_ons_of_a_bundle_off_and_on(self, client, served, monkeypatch):  # noqa: F811
        load(client, served)
        installed(client, monkeypatch, info("docx"))

        client.bundles.set_enabled("office", False)
        assert "docx" in client.addons._manager.disabled_ids()  # noqa: SLF001

        client.bundles.set_enabled("office", True)
        assert "docx" not in client.addons._manager.disabled_ids()  # noqa: SLF001

    def test_an_unlisted_bundle_or_one_with_nothing_installed_raises(self, client, served):  # noqa: F811
        load(client, served)

        with pytest.raises(ValueError, match="No bundle"):
            client.bundles.set_enabled("nope", False)
        with pytest.raises(ValueError, match="No add-on of the office bundle"):
            client.bundles.set_enabled("office", False)
