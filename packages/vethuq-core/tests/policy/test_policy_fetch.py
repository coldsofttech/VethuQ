import socket

from vethuq_core.policy.fetch import FetchFailure, FetchResponse, PolicyFetcher


def fetcher(*urls, **kwargs):
    return PolicyFetcher(urls, schemes=("http", "https"), **kwargs)


def test_fetches_body_and_etag(server):
    server.serve("/v1/policy.json", b"hello", ETag='"v1"')
    (result,) = fetcher(server.url()).attempts()
    assert result == FetchResponse(server.url(), b"hello", '"v1"')


def test_sends_etag_only_to_the_url_it_came_from(server):
    server.serve("/a", b"A", ETag='"a"')
    server.serve("/b", b"B")
    results = list(fetcher(server.url("/a"), server.url("/b")).attempts(server.url("/a"), '"a"'))
    assert results[0].not_modified
    assert results[1].body == b"B"
    sent = {path: headers.get("If-None-Match") for path, headers in server.requests}
    assert sent == {"/a": '"a"', "/b": None}


def test_http_errors_and_unreachable_hosts_fall_through(server):
    server.serve("/ok", b"fine")
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    dead_port = closed.getsockname()[1]
    closed.close()
    results = list(
        fetcher(
            f"http://127.0.0.1:{dead_port}/x", server.url("/missing"), server.url("/ok")
        ).attempts()
    )
    assert isinstance(results[0], FetchFailure)
    assert results[1] == FetchFailure(server.url("/missing"), "HTTP 404")
    assert results[2].body == b"fine"


def test_oversized_body_is_refused(server):
    server.serve("/big", b"x" * 100)
    (result,) = fetcher(server.url("/big"), max_bytes=50).attempts()
    assert isinstance(result, FetchFailure) and "large" in result.reason


def test_slow_server_times_out():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)  # accepts connections but never answers
    url = f"http://127.0.0.1:{listener.getsockname()[1]}/p"
    try:
        (result,) = fetcher(url, timeout=0.3).attempts()
    finally:
        listener.close()
    assert isinstance(result, FetchFailure)


def test_plain_http_is_refused_by_default(server):
    server.serve("/v1/policy.json", b"x")
    (result,) = PolicyFetcher([server.url()]).attempts()
    assert isinstance(result, FetchFailure)
    assert server.requests == []
