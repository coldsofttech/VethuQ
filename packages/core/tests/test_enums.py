from __future__ import annotations

import json

import pytest

import vethuq
from vethuq import enums


class TestEnums:
    def test_source_type_values(self):
        assert [t.value for t in vethuq.SourceType] == ["file", "folder"]

    def test_source_status_values(self):
        assert [s.value for s in vethuq.SourceStatus] == [
            "pending",
            "indexed",
            "error",
            "removed",
        ]

    def test_sort_order_values(self):
        assert [o.value for o in vethuq.SortOrder] == ["asc", "desc"]

    def test_sort_by_values(self):
        assert [f.value for f in vethuq.SourceSortBy] == [
            "id",
            "path",
            "status",
            "source_type",
            "added_at",
            "last_scanned_at",
        ]

    @pytest.mark.parametrize(
        "member",
        [*vethuq.SourceType, *vethuq.SourceStatus, *vethuq.SortOrder, *vethuq.SourceSortBy],
    )
    def test_members_are_strings_equal_to_their_values(self, member):
        assert isinstance(member, str)
        assert member == member.value
        assert json.dumps(member) == f'"{member.value}"'
        assert type(member)(member.value) is member

    def test_are_exported_from_the_package(self):
        for name in enums.__all__:
            assert getattr(vethuq, name) is getattr(enums, name)
