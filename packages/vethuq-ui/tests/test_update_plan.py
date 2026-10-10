import pytest
from vethuq_core.settings import UpdateSettings
from vethuq_core.storage.sqlite import SqliteStorage
from vethuq_core.updates import UpdateResult, UpdateStatus
from vethuq_ui.update_plan import UpdatePlan


def result(status=UpdateStatus.AVAILABLE, **fields):
    base = {
        "mode": "on",
        "current": "1.0.0",
        "distribution": "desktop",
        "latest": "1.2.0",
        "minimum_supported": "1.0.0",
    }
    return UpdateResult(status, **{**base, **fields})


@pytest.fixture
def storage(tmp_path):
    from vethuq_core.db import Db

    conn = Db.connect(tmp_path / "vethuq.db")
    yield SqliteStorage(conn)
    conn.close()


class TestForResult:
    def test_a_newer_version_opens_a_dialog_with_later_and_skip(self):
        plan = UpdatePlan.for_result(result(release_notes_url="https://example.com/n"))

        assert plan is not None and plan.kind == "dialog"
        assert [action for action, _ in plan.choices] == [UpdatePlan.LATER, UpdatePlan.SKIP]
        assert "1.2.0" in plan.message and plan.release_notes_url == "https://example.com/n"

    def test_notify_only_uses_the_status_bar_not_a_dialog(self):
        plan = UpdatePlan.for_result(result(mode="notify-only"))

        assert plan is not None and plan.kind == "message"

    def test_below_minimum_can_only_be_acknowledged(self):
        plan = UpdatePlan.for_result(result(UpdateStatus.BELOW_MINIMUM, minimum_supported="1.1.0"))

        assert plan is not None
        assert [action for action, _ in plan.choices] == [UpdatePlan.OK]
        assert "local features keep working" in plan.message.lower()

    @pytest.mark.parametrize(
        "found",
        [
            result(UpdateStatus.UP_TO_DATE, current="1.2.0"),
            result(UpdateStatus.DISABLED),
            result(UpdateStatus.UNKNOWN, latest=None),
            result(snoozed=True),
            result(skipped=True),
        ],
    )
    def test_nothing_to_say(self, found):
        assert UpdatePlan.for_result(found) is None

    def test_a_policy_that_needs_a_newer_client_gets_a_later_choice(self):
        plan = UpdatePlan.for_result(
            result(UpdateStatus.UP_TO_DATE, current="1.2.0", policy_update_required=True)
        )

        assert plan is not None
        assert [action for action, _ in plan.choices] == [UpdatePlan.LATER]


class TestApply:
    def test_later_snoozes(self, storage):
        said = []

        UpdatePlan.apply(storage, result(), UpdatePlan.LATER, said.append)

        assert UpdateSettings.is_snoozed(storage) and said

    def test_skip_remembers_that_version(self, storage):
        said = []

        UpdatePlan.apply(storage, result(), UpdatePlan.SKIP, said.append)

        assert UpdateSettings.get_skipped_version(storage) == "1.2.0"
        assert "1.2.0" in said[0]

    def test_ok_changes_nothing(self, storage):
        UpdatePlan.apply(storage, result(), UpdatePlan.OK, lambda _text: None)

        assert not UpdateSettings.is_snoozed(storage)
        assert UpdateSettings.get_skipped_version(storage) is None
