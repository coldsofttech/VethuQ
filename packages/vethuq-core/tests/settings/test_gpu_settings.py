from vethuq_core.settings import GpuSettings
from vethuq_core.storage import Storage


class TestGpuSettings:
    def test_disabled_by_default(self, storage: Storage):
        assert GpuSettings.is_enabled(storage) is False

    def test_reset_disables_gpu(self, storage: Storage):
        GpuSettings.set_enabled(storage, True)

        GpuSettings.reset(storage)

        assert GpuSettings.is_enabled(storage) is False
