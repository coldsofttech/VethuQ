import pytest
from vethuq_core.updates import Versions


@pytest.mark.parametrize(
    "have,wanted,older",
    [
        ("1.0.0", "1.2.0", True),
        ("1.2.0", "1.2.0", False),
        ("1.3.0", "1.2.0", False),
        ("1.2.0rc1", "1.2.0", True),  # PEP 440 pre-release of the pip package
        ("1.2.0-rc.1", "1.2.0", True),  # the policy's spelling of the same thing
        ("1.2.0-rc.1", "1.2.0rc2", True),
        ("1.10.0", "1.9.0", False),  # numeric, not text, ordering
    ],
)
def test_is_older(have, wanted, older):
    assert Versions.is_older(have, wanted) is older


@pytest.mark.parametrize("text", ["unknown", "", None, "banana"])
def test_unparseable_versions_are_never_older(text):
    assert Versions.parse(text) is None
    assert Versions.is_older(text, "1.0.0") is False
    assert Versions.is_older("1.0.0", text) is False
