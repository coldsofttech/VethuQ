from vethuq_core.settings import IndexSettings, SourceSettings
from vethuq_core.storage import Storage


class TestIndexSettingsReset:
    def test_reset_thread_workers_goes_back_to_disabled(self, storage: Storage):
        IndexSettings.set_thread_workers(storage, "4")

        IndexSettings.reset_thread_workers(storage)

        assert IndexSettings.get_thread_workers(storage) == IndexSettings.DEFAULT_THREAD_WORKERS

    def test_reset_stale_lock_goes_back_to_auto(self, storage: Storage):
        IndexSettings.set_stale_lock(storage, "disable")

        IndexSettings.reset_stale_lock(storage)

        assert IndexSettings.get_stale_lock(storage) == IndexSettings.DEFAULT_STALE_LOCK

    def test_reset_removed_retention_goes_back_to_default(self, storage: Storage):
        SourceSettings.set_removed_retention_minutes(storage, 5)

        SourceSettings.reset_removed_retention_minutes(storage)

        assert (
            SourceSettings.get_removed_retention_minutes(storage)
            == SourceSettings.DEFAULT_REMOVED_RETENTION_MINUTES
        )
