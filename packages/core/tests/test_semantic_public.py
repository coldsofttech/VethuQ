"""Semantic search end to end: the real add-on (with a stand-in embedding model), the real
sub-wallet, `Search.sync`, `engine="semantic"` and `engine="hybrid"`."""

from __future__ import annotations

import hashlib
import re

import pytest

np = pytest.importorskip("numpy")
semantic = pytest.importorskip("vethuq_addon_semantic")

import vethuq  # noqa: E402
from tests import fake_pipeline as fp  # noqa: E402
from vethuq import errors  # noqa: E402

CONCEPTS = {"refund": "money-back", "reimbursement": "money-back", "car": "vehicle"}


class FakeEmbedder:
    """Words hashed into a small space; synonyms share a concept."""

    model = "fake-embedder"

    @staticmethod
    def _vector(text):
        vector = np.zeros(64, dtype=np.float32)
        for word in re.findall(r"\w+", text.casefold()):
            digest = hashlib.sha256(CONCEPTS.get(word, word).encode()).digest()
            vector[digest[0] % 64] += 1.0 if digest[1] % 2 else -1.0
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def embed_passages(self, texts):
        return np.array([self._vector(t) for t in texts], dtype=np.float32).reshape(len(texts), 64)

    def embed_query(self, text):
        return self._vector(text)


PAGES = {
    "refund.pdf": ["Refund policy."],
    "garage.pdf": ["The garage fixes the car.", "Opening hours."],
    "terms.pdf": ["Refund rules apply."],
}


@pytest.fixture(autouse=True)
def stand_in_model(monkeypatch):
    embedder = FakeEmbedder()
    monkeypatch.setattr(semantic.SemanticAddon, "embedder_factory", staticmethod(lambda: embedder))


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        yield client


@pytest.fixture
def indexed(client, tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    for name, texts in PAGES.items():
        (root / name).write_text(fp.pdf_document(*(fp.native_page(t) for t in texts)))
    client.sources.create(root)
    assert client.index.run().status.value == "completed"
    return client


def wallet(client):
    return client.credits.balance("semantic")


def files(result):
    return list(dict.fromkeys(m.file_name for m in result))


class TestTheEngine:
    def test_it_is_installed_but_not_part_of_all(self, client):
        info = {e.id: e for e in client.search.engines()}["semantic"]
        assert info.available and not info.in_all and info.approximate
        assert set(info.options) == {"threshold", "limit"}

    def test_the_wallet_is_listed_with_its_allowance(self, client):
        assert client.credits.wallets() == ["local", "semantic"]
        assert wallet(client).daily == 50.0


class TestPreparingAndSearching:
    def test_nothing_is_found_until_pages_are_prepared(self, indexed):
        result = indexed.search.run(
            "reimbursement", engine="semantic", options="semantic.threshold=0.5"
        )
        assert result.total == 0 and result.pending == {"semantic": 4}

    def test_sync_prepares_pages_and_pays_from_the_sub_wallet(self, indexed):
        local = indexed.credits.balance("local").total
        before = wallet(indexed).total
        steps = []
        (report,) = indexed.search.sync("semantic", progress=lambda e, d, t: steps.append((d, t)))
        assert (report.engine, report.pages, report.pending, report.paused) == (
            "semantic",
            4,
            0,
            False,
        )
        assert report.credits == 2.0 and steps == [(4, 4)]
        assert wallet(indexed).total == before - 2.0
        assert indexed.credits.balance("local").total == local  # OCR credits are not touched
        (entry, *_) = indexed.credits.history(kind="charge", wallet="semantic")
        assert (entry.wallet, entry.amount) == ("semantic", 2.0)

    def test_after_sync_meaning_finds_the_page_without_its_words(self, indexed):
        indexed.search.sync("semantic")
        result = indexed.search.run(
            "reimbursement", engine="semantic", options="semantic.threshold=0.5"
        )
        assert result.pending == {} and result.engine == "semantic"
        assert files(result) == ["refund.pdf", "terms.pdf"]
        assert all(m.engine == "semantic" and m.score and m.score >= 0.5 for m in result)
        assert result[0].matched == "Refund policy."

    def test_searching_is_free(self, indexed):
        indexed.search.sync("semantic")
        before = wallet(indexed).total
        indexed.search.run("reimbursement", engine="semantic", options="semantic.threshold=0.5")
        assert wallet(indexed).total == before

    def test_a_second_sync_costs_nothing(self, indexed):
        indexed.search.sync("semantic")
        before = wallet(indexed).total
        (report,) = indexed.search.sync("semantic")
        assert (report.pages, report.credits) == (0, 0.0) and wallet(indexed).total == before

    def test_new_files_are_prepared_by_the_next_sync(self, indexed, tmp_path):
        indexed.search.sync("semantic")
        (tmp_path / "docs" / "new.pdf").write_text(fp.pdf_document(fp.native_page("Another car.")))
        indexed.index.run()
        result = indexed.search.run("car", engine="semantic", options="semantic.threshold=0.5")
        assert result.pending == {"semantic": 1}
        (report,) = indexed.search.sync("semantic")
        assert report.pages == 1
        assert "new.pdf" in files(
            indexed.search.run("car", engine="semantic", options="semantic.threshold=0.5")
        )

    def test_running_out_of_credits_pauses_the_sync(self, indexed):
        addon = indexed._manager().loaded()["semantic"].addon
        credits = addon.host.credits
        credits.charge(credits.balance_milli() - 700)  # enough for one page, not two
        addon.engine().PAGES_PER_BATCH = 1
        (report,) = indexed.search.sync("semantic")
        assert (report.pages, report.pending, report.paused) == (1, 3, True)
        assert "credits" in report.message and report.credits == 0.5
        # what was prepared is searchable, and the rest is reported as pending
        result = indexed.search.run(
            "reimbursement", engine="semantic", options="semantic.threshold=0.5"
        )
        assert result.pending == {"semantic": 3}
        # the credits come back (a licence grant, tomorrow's allowance): the next sync carries on
        credits.charge(0)
        service = indexed._credit_engine()
        with indexed._db().session() as session:
            service.sync(session, "semantic")
            service.wallet_for("semantic").add_one_off(
                session, "grant:test", 10_000, "licence", scope=None, expires=None
            )
        (report,) = indexed.search.sync("semantic")
        assert (report.pages, report.pending, report.paused) == (3, 0, False)

    def test_hybrid_ranks_meaning_and_words_together(self, indexed):
        indexed.search.sync("semantic")
        result = indexed.search.run(
            "reimbursement",
            engine="hybrid",
            combine="full-text",
            options="semantic.threshold=0.5",
        )
        assert result.engine == "hybrid"
        assert files(result) == ["refund.pdf", "terms.pdf"]
        assert {m.engine for m in result} == {"semantic"}  # the words aren't on those pages
        both = indexed.search.run("refund", engine="hybrid", options="semantic.threshold=0.5")
        assert {m.engine for m in both} == {"semantic", "full-text"}
        found_by_both = [m for m in both if m.file_name == "refund.pdf"]
        assert {m.matched_by for m in found_by_both} == {("full-text", "semantic")}

    def test_hybrid_before_sync_is_still_a_keyword_search(self, indexed):
        result = indexed.search.run("refund", engine="hybrid")
        assert {m.engine for m in result} == {"full-text"} and result.pending == {"semantic": 4}

    def test_the_default_engine_can_be_hybrid(self, indexed):
        indexed.settings.search.set_engine("hybrid")
        assert indexed.search.run("refund").engine == "hybrid"


class TestWithoutTheModelLibraries:
    def test_it_is_listed_as_unavailable_and_says_what_it_needs(self, client, monkeypatch):
        monkeypatch.setattr(semantic.SemanticAddon, "embedder_factory", None)
        monkeypatch.setattr("vethuq_addon_semantic._addon.find_spec", lambda name: None)
        info = {e.id: e for e in client.search.engines()}["semantic"]
        assert not info.available and "onnxruntime" in info.reason
        with pytest.raises(errors.SearchUnavailableError, match="can't be used"):
            client.search.run("x", engine="semantic")
        with pytest.raises(errors.SearchUnavailableError, match="can't be used"):
            client.search.sync("semantic")
        with pytest.raises(errors.SearchUnavailableError, match="hybrid"):
            client.search.run("x", engine="hybrid")

    def test_syncing_with_the_model_not_downloaded_tells_how_to_fetch_it(self, client, monkeypatch):
        monkeypatch.setattr(semantic.SemanticAddon, "embedder_factory", None)
        monkeypatch.setattr("vethuq_addon_semantic._addon.find_spec", lambda name: object())
        monkeypatch.setitem(__import__("sys").modules, "huggingface_hub", None)
        with pytest.raises(errors.SearchUnavailableError, match="huggingface_hub"):
            client.search.sync("semantic")


class TestWhenTheDatabaseChanges:
    """The vectors are the add-on's own file; the database can change under it."""

    OPTIONS = "semantic.threshold=0.5"

    @staticmethod
    def stored(client):
        return client._manager().loaded()["semantic"].addon.engine().store.counts()[0]

    def test_a_purged_source_is_forgotten_by_the_next_sync_and_never_found(self, indexed):
        indexed.search.sync("semantic")
        assert self.stored(indexed) == 4
        source = indexed.sources.list()[0]
        indexed.sources.remove(source.id)
        indexed.sources.purge(source.id)
        result = indexed.search.run("reimbursement", engine="semantic", options=self.OPTIONS)
        assert result.total == 0  # the old vectors are not used for pages that are gone
        indexed.search.sync("semantic")
        assert self.stored(indexed) == 0

    def test_a_sync_that_ran_out_of_credits_still_forgets_what_is_gone(self, indexed, tmp_path):
        indexed.search.sync("semantic")
        source = indexed.sources.list()[0]
        indexed.sources.remove(source.id)
        indexed.sources.purge(source.id)
        other = tmp_path / "other"
        other.mkdir()
        (other / "new.pdf").write_text(fp.pdf_document(fp.native_page("Something new.")))
        indexed.sources.create(other)
        indexed.index.run()
        addon = indexed._manager().loaded()["semantic"].addon
        addon.host.credits.charge(addon.host.credits.balance_milli())  # nothing left to spend
        (report,) = indexed.search.sync("semantic")
        assert report.paused and self.stored(indexed) == 0

    def test_a_new_database_with_new_ids_does_not_reuse_old_vectors(self, indexed, tmp_path):
        indexed.search.sync("semantic")
        source = indexed.sources.list()[0]
        indexed.sources.remove(source.id)
        indexed.sources.purge(source.id)
        other = tmp_path / "other"
        other.mkdir()
        (other / "unrelated.pdf").write_text(fp.pdf_document(fp.native_page("Gardening tips.")))
        indexed.sources.create(other)
        indexed.index.run()
        # the new page may take an id the old one had; its text differs, so it is pending
        result = indexed.search.run("reimbursement", engine="semantic", options=self.OPTIONS)
        assert result.total == 0 and result.pending == {"semantic": 1}
        indexed.search.sync("semantic")
        assert self.stored(indexed) == 1

    def test_turning_the_addon_off_and_on_keeps_its_vectors(self, indexed):
        indexed.search.sync("semantic")
        indexed.addons.set_enabled("semantic", False)
        indexed.addons.set_enabled("semantic", True)
        assert self.stored(indexed) == 4
        result = indexed.search.run("reimbursement", engine="semantic", options=self.OPTIONS)
        assert files(result) == ["refund.pdf", "terms.pdf"]
