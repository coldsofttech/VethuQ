import pytest
from vethuq_core.policy import PolicyClient, PolicyUrls

VAR = PolicyUrls.ENV_VAR


def test_defaults_are_the_three_published_urls():
    assert PolicyUrls.resolve({}) == PolicyUrls.DEFAULT
    assert len(PolicyUrls.DEFAULT) == 3
    assert all(url.startswith("https://") for url in PolicyUrls.DEFAULT)


def test_the_variable_replaces_the_defaults_in_order():
    env = {VAR: "https://a.example/p.json,https://b.example/p.json"}
    assert PolicyUrls.resolve(env) == ("https://a.example/p.json", "https://b.example/p.json")


def test_whitespace_and_duplicates_are_tolerated():
    env = {VAR: " https://a.example/p.json ,\nhttps://b.example/p.json  https://a.example/p.json "}
    assert PolicyUrls.resolve(env) == ("https://a.example/p.json", "https://b.example/p.json")


def test_a_mirror_can_keep_the_public_urls_as_fallbacks():
    env = {VAR: ",".join(("https://mirror.corp/p.json", *PolicyUrls.DEFAULT))}
    assert PolicyUrls.resolve(env) == ("https://mirror.corp/p.json", *PolicyUrls.DEFAULT)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "http://insecure.example/p.json",
        "ftp://x/p",
        "not a url",
        "https://",
        "file:///etc/passwd",
    ],
)
def test_unusable_values_fall_back_to_the_defaults(value):
    assert PolicyUrls.resolve({VAR: value}) == PolicyUrls.DEFAULT


def test_unusable_entries_are_dropped_but_good_ones_kept():
    env = {VAR: "http://bad.example/p,https://good.example/p.json"}
    assert PolicyUrls.resolve(env) == ("https://good.example/p.json",)


def test_the_client_reads_the_process_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(VAR, "https://staging.example/v1/policy.json")
    client = PolicyClient(cache_dir=tmp_path)
    assert client._fetcher.urls == ("https://staging.example/v1/policy.json",)
    monkeypatch.delenv(VAR)
    assert PolicyClient(cache_dir=tmp_path)._fetcher.urls == PolicyUrls.DEFAULT


def test_an_explicit_urls_argument_wins_over_the_variable(monkeypatch, tmp_path):
    monkeypatch.setenv(VAR, "https://staging.example/p.json")
    client = PolicyClient(urls=("https://explicit.example/p.json",), cache_dir=tmp_path)
    assert client._fetcher.urls == ("https://explicit.example/p.json",)
