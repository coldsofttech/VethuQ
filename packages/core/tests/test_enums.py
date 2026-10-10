from __future__ import annotations

import json

import pytest

import vethuq
from vethuq import enums


class TestEnums:
    def test_addon_status_values(self):
        assert [s.value for s in enums.AddonStatus] == ["loaded", "incompatible", "failed"]

    def test_source_type_values(self):
        assert [t.value for t in enums.SourceType] == ["file", "folder"]

    def test_source_status_values(self):
        assert [s.value for s in enums.SourceStatus] == [
            "pending",
            "indexed",
            "error",
            "removed",
        ]

    def test_sort_order_values(self):
        assert [o.value for o in enums.SortOrder] == ["asc", "desc"]

    def test_sort_by_values(self):
        assert [f.value for f in enums.SourceSortBy] == [
            "id",
            "path",
            "status",
            "source_type",
            "added_at",
            "last_scanned_at",
        ]

    def test_log_component_values(self):
        assert [c.value for c in enums.LogComponent] == ["database", "index", "ui", "cli", "policy"]

    def test_log_level_values_run_from_least_to_most_severe(self):
        assert [level.value for level in enums.LogLevel] == ["debug", "info", "warning", "error"]

    @pytest.mark.parametrize(
        "member",
        [
            *enums.SourceType,
            *enums.SourceStatus,
            *enums.SortOrder,
            *enums.SourceSortBy,
            *enums.LogComponent,
            *enums.LogLevel,
        ],
    )
    def test_members_are_strings_equal_to_their_values(self, member):
        assert isinstance(member, str)
        assert member == member.value
        assert json.dumps(member) == f'"{member.value}"'
        assert type(member)(member.value) is member

    @pytest.mark.parametrize(
        "name", ["SourceType", "SourceStatus", "SortOrder", "SourceSortBy"]
    )
    def test_source_enums_are_available_from_vethuq_sources(self, name):
        assert getattr(vethuq.sources, name) is getattr(enums, name)
        assert name in vethuq.sources.__all__

    @pytest.mark.parametrize("name", ["LogComponent", "LogLevel", "SortOrder"])
    def test_log_enums_are_available_from_vethuq_logs(self, name):
        assert getattr(vethuq.logs, name) is getattr(enums, name)
        assert name in vethuq.logs.__all__

    def test_sort_order_is_one_enum_for_sources_and_logs(self):
        assert vethuq.sources.SortOrder is vethuq.logs.SortOrder

    @pytest.mark.parametrize("name", enums.__all__)
    def test_they_are_not_top_level_names(self, name):
        assert not hasattr(vethuq, name)
