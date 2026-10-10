import json
import os

from vethuq_core.policy.state import PolicyState, PolicyStore


def test_state_round_trips(tmp_path):
    store = PolicyStore(tmp_path / "policy")
    state = PolicyState(
        accepted={"a": 4},
        revoked=frozenset({"x"}),
        etag='"e"',
        etag_url="https://u",
        last_check=12.5,
        update_required=True,
    )
    store.write_state(state)
    assert store.read_state() == state


def test_missing_or_corrupt_files_read_as_empty(tmp_path):
    store = PolicyStore(tmp_path)
    assert store.read_state() == PolicyState()
    assert store.read_envelope() is None
    (tmp_path / "state.json").write_text("{not json", encoding="utf-8")
    assert store.read_state() == PolicyState()


def test_wrongly_typed_fields_are_dropped(tmp_path):
    (tmp_path / "state.json").write_text(
        json.dumps({"accepted": {"a": "x", "b": 2, "c": True}, "revoked": [1, "r"], "etag": 5}),
        encoding="utf-8",
    )
    state = PolicyStore(tmp_path).read_state()
    assert state.accepted == {"b": 2}
    assert state.revoked == frozenset({"r"})
    assert state.etag is None


def test_write_is_atomic_and_leaves_no_temp_files(tmp_path):
    store = PolicyStore(tmp_path)
    store.write_envelope(b"one")
    store.write_envelope(b"two")
    assert store.read_envelope() == b"two"
    assert sorted(os.listdir(tmp_path)) == ["policy.json"]


def test_a_failed_write_keeps_the_previous_file(tmp_path, monkeypatch):
    store = PolicyStore(tmp_path)
    store.write_envelope(b"good")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    try:
        store.write_envelope(b"new")
    except OSError:
        pass
    assert store.read_envelope() == b"good"
    assert sorted(os.listdir(tmp_path)) == ["policy.json"]
