from __future__ import annotations

import inspect
import ipaddress
import socket

import pytest
import requests
from fastapi import HTTPException

from app.routers import llm as llm_router
from app.services import analyzer


PUBLIC_IPV4 = ipaddress.ip_address("93.184.216.34")
PUBLIC_IPV6 = ipaddress.ip_address("2606:4700:4700::1111")


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        chunks: tuple[bytes, ...] = (),
        encoding: str | None = "utf-8",
    ) -> None:
        self.status_code = status_code
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})
        self.chunks = chunks
        self.encoding = encoding
        self.closed = False
        self.iterated = False

    def iter_content(self, chunk_size: int):
        self.iterated = True
        assert chunk_size == analyzer.DOWNLOAD_CHUNK_SIZE
        yield from self.chunks

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError("raw upstream HTTP failure")

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[FakeResponse | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []
        self.trust_env = True
        self.closed = False

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def prevent_real_network(monkeypatch):
    def unexpected_dns(*_args, **_kwargs):
        raise AssertionError("unexpected real DNS lookup")

    def unexpected_session():
        raise AssertionError("unexpected real HTTP session")

    monkeypatch.setattr(analyzer.socket, "getaddrinfo", unexpected_dns)
    monkeypatch.setattr(analyzer.requests, "Session", unexpected_session)


def allow_public_dns(monkeypatch, *addresses):
    resolved = addresses or (PUBLIC_IPV4,)
    monkeypatch.setattr(
        analyzer,
        "_resolve_host_addresses",
        lambda _hostname, _port: tuple(resolved),
    )


def install_session(monkeypatch, *responses):
    session = FakeSession(list(responses))
    monkeypatch.setattr(analyzer.requests, "Session", lambda: session)
    return session


def html_response(
    body: bytes = b"<html><body>ok</body></html>",
    *,
    content_type: str = "text/html; charset=utf-8",
) -> FakeResponse:
    return FakeResponse(
        headers={"Content-Type": content_type},
        chunks=(body,),
    )


def assert_url_blocked(url: str) -> None:
    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.validate_and_resolve_url(url)
    assert exc_info.value.status_code == 400
    assert exc_info.value.public_message == analyzer.INVALID_URL_MESSAGE


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://public.example/path", "http://public.example/path"),
        ("https://public.example/path?q=1", "https://public.example/path?q=1"),
        ("public.example:443/path", "https://public.example:443/path"),
    ],
)
def test_public_http_and_https_urls_are_accepted(monkeypatch, url, expected):
    allow_public_dns(monkeypatch, PUBLIC_IPV4, PUBLIC_IPV6)
    assert analyzer.validate_and_resolve_url(url) == expected


def test_unsupported_scheme_is_rejected():
    assert_url_blocked("file:///etc/passwd")


def test_malformed_url_is_rejected():
    assert_url_blocked("http:///missing-host")


def test_embedded_credentials_are_rejected():
    assert_url_blocked("https://user:password@public.example/")


def test_localhost_is_rejected():
    assert_url_blocked("http://localhost/")


def test_local_style_hostname_is_rejected():
    assert_url_blocked("http://service.local/")


def test_loopback_ipv4_is_rejected():
    assert_url_blocked("http://127.0.0.1/")


@pytest.mark.parametrize("address", ["10.0.0.1", "172.16.0.1", "192.168.1.1"])
def test_private_ipv4_is_rejected(address):
    assert_url_blocked(f"http://{address}/")


def test_link_local_metadata_address_is_rejected():
    assert_url_blocked("http://169.254.169.254/latest/meta-data/")


def test_ipv6_loopback_is_rejected():
    assert_url_blocked("http://[::1]/")


@pytest.mark.parametrize(
    "url",
    [
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/latest/meta-data/",
    ],
)
def test_unsafe_ipv4_mapped_ipv6_is_rejected(url):
    assert_url_blocked(url)


def test_private_ipv6_is_rejected():
    assert_url_blocked("http://[fd00::1]/")


def test_deprecated_site_local_ipv6_is_rejected():
    assert_url_blocked("http://[fec0::1]/")


def test_nonstandard_port_is_rejected(monkeypatch):
    allow_public_dns(monkeypatch)
    assert_url_blocked("https://public.example:8080/")


def test_mixed_public_and_private_dns_answer_is_rejected(monkeypatch):
    allow_public_dns(monkeypatch, PUBLIC_IPV4, ipaddress.ip_address("10.0.0.8"))
    assert_url_blocked("https://public.example/")


def test_dns_failure_is_sanitized(monkeypatch):
    def fail_dns(*_args, **_kwargs):
        raise socket.gaierror("raw resolver detail for internal.example")

    monkeypatch.setattr(analyzer.socket, "getaddrinfo", fail_dns)
    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.validate_and_resolve_url("https://public.example/")

    assert exc_info.value.status_code == 502
    assert exc_info.value.public_message == analyzer.FETCH_FAILED_MESSAGE
    assert "internal.example" not in str(exc_info.value)


@pytest.mark.parametrize(
    "hostname",
    [
        "127.1",
        "0x7f.0x0.0x0.0x1",
    ],
)
def test_resolver_normalized_loopback_forms_are_rejected(monkeypatch, hostname):
    def resolve_as_loopback(resolved_hostname, port, **kwargs):
        assert resolved_hostname == hostname
        assert port == 80
        assert kwargs == {
            "family": socket.AF_UNSPEC,
            "type": socket.SOCK_STREAM,
            "proto": socket.IPPROTO_TCP,
        }
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("127.0.0.1", port),
            )
        ]

    monkeypatch.setattr(analyzer.socket, "getaddrinfo", resolve_as_loopback)
    assert_url_blocked(f"http://{hostname}/")


def test_integer_ipv4_loopback_form_is_rejected():
    assert_url_blocked("http://2130706433/")


def test_public_to_public_redirect_is_followed(monkeypatch):
    allow_public_dns(monkeypatch)
    redirect = FakeResponse(
        status_code=302,
        headers={"Location": "https://next.example/final"},
    )
    final = html_response()
    session = install_session(monkeypatch, redirect, final)

    assert analyzer.fetch_html("https://public.example/start") == "<html><body>ok</body></html>"
    assert [url for url, _kwargs in session.calls] == [
        "https://public.example/start",
        "https://next.example/final",
    ]
    assert all(not kwargs["allow_redirects"] for _url, kwargs in session.calls)
    assert all(kwargs["stream"] for _url, kwargs in session.calls)
    assert session.trust_env is False
    assert redirect.closed and final.closed and session.closed


def test_public_to_private_redirect_is_rejected(monkeypatch):
    allow_public_dns(monkeypatch)
    redirect = FakeResponse(
        status_code=302,
        headers={"Location": "http://127.0.0.1/admin"},
    )
    session = install_session(monkeypatch, redirect)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/start")

    assert exc_info.value.status_code == 400
    assert len(session.calls) == 1
    assert redirect.closed and session.closed


def test_relative_redirect_is_resolved(monkeypatch):
    allow_public_dns(monkeypatch)
    redirect = FakeResponse(status_code=301, headers={"Location": "../final"})
    final = html_response(b"<html>relative</html>")
    session = install_session(monkeypatch, redirect, final)

    assert analyzer.fetch_html("https://public.example/path/start") == "<html>relative</html>"
    assert session.calls[1][0] == "https://public.example/final"


def test_scheme_relative_redirect_is_resolved(monkeypatch):
    allow_public_dns(monkeypatch)
    redirect = FakeResponse(status_code=302, headers={"Location": "//example.com/path"})
    final = html_response(b"<html>scheme-relative</html>")
    session = install_session(monkeypatch, redirect, final)

    assert analyzer.fetch_html("https://public.example/start") == "<html>scheme-relative</html>"
    assert session.calls[1][0] == "https://example.com/path"


def test_redirect_limit_is_enforced(monkeypatch):
    allow_public_dns(monkeypatch)
    redirects = [
        FakeResponse(status_code=302, headers={"Location": f"/hop-{number}"})
        for number in range(1, 5)
    ]
    session = install_session(monkeypatch, *redirects)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/start", maximum_redirects=3)

    assert exc_info.value.status_code == 502
    assert len(session.calls) == 4
    assert all(response.closed for response in redirects)
    assert session.closed


def test_redirect_loop_is_rejected(monkeypatch):
    allow_public_dns(monkeypatch)
    redirect = FakeResponse(status_code=302, headers={"Location": "/start"})
    session = install_session(monkeypatch, redirect)

    with pytest.raises(analyzer.SiteFetchError):
        analyzer.fetch_html("https://public.example/start")

    assert len(session.calls) == 1
    assert redirect.closed and session.closed


def test_redirect_with_credentials_is_rejected(monkeypatch):
    allow_public_dns(monkeypatch)
    redirect = FakeResponse(
        status_code=302,
        headers={"Location": "https://user:secret@next.example/"},
    )
    session = install_session(monkeypatch, redirect)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/start")

    assert exc_info.value.status_code == 400
    assert len(session.calls) == 1


def test_oversized_content_length_is_rejected(monkeypatch):
    allow_public_dns(monkeypatch)
    response = FakeResponse(
        headers={
            "Content-Type": "text/html",
            "Content-Length": str(analyzer.MAX_RESPONSE_BYTES + 1),
        }
    )
    session = install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/")

    assert exc_info.value.status_code == 413
    assert response.closed and session.closed


def test_streamed_body_over_limit_is_rejected(monkeypatch):
    allow_public_dns(monkeypatch)
    response = FakeResponse(
        headers={"Content-Type": "text/html"},
        chunks=(b"12345", b"678901"),
    )
    install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/", maximum_bytes=10)

    assert exc_info.value.status_code == 413


def test_unsupported_content_type_is_rejected(monkeypatch):
    allow_public_dns(monkeypatch)
    response = FakeResponse(
        headers={"Content-Type": "application/pdf"},
        chunks=(b"%PDF",),
    )
    install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/document")

    assert exc_info.value.status_code == 415


def test_missing_content_type_is_rejected(monkeypatch):
    allow_public_dns(monkeypatch)
    install_session(monkeypatch, FakeResponse(chunks=(b"<html>missing header</html>",)))

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/")

    assert exc_info.value.status_code == 415


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "text/html"},
        {"Content-Type": "text/html", "Content-Encoding": "identity"},
        {"Content-Type": "text/html", "content-encoding": "  IdEnTiTy\t"},
    ],
)
def test_identity_or_missing_content_encoding_is_accepted(monkeypatch, headers):
    allow_public_dns(monkeypatch)
    response = FakeResponse(headers=headers, chunks=(b"<html>ok</html>",))
    install_session(monkeypatch, response)

    assert analyzer.fetch_html("https://public.example/") == "<html>ok</html>"
    assert response.iterated


@pytest.mark.parametrize("content_encoding", ["gzip", "deflate", "br", "  GZip\t"])
def test_compressed_content_encoding_is_rejected_before_iteration(
    monkeypatch,
    content_encoding,
):
    allow_public_dns(monkeypatch)
    response = FakeResponse(
        headers={"Content-Type": "text/html", "Content-Encoding": content_encoding},
        chunks=(b"compressed bytes",),
    )
    session = install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/")

    assert exc_info.value.status_code == 415
    assert exc_info.value.public_message == analyzer.UNSUPPORTED_CONTENT_ENCODING_MESSAGE
    assert not response.iterated
    assert response.closed and session.closed


@pytest.mark.parametrize("content_type", ["text/html", "application/xhtml+xml"])
def test_valid_bounded_html_is_accepted(monkeypatch, content_type):
    allow_public_dns(monkeypatch)
    response = html_response(
        "<html><body>Привет</body></html>".encode("cp1251"),
        content_type=content_type,
    )
    response.encoding = "cp1251"
    session = install_session(monkeypatch, response)

    html = analyzer.fetch_html("https://public.example/")

    assert "Привет" in html
    assert session.calls[0][1]["headers"]["Accept-Encoding"] == "identity"


def test_network_failure_is_sanitized(monkeypatch):
    allow_public_dns(monkeypatch)
    session = install_session(
        monkeypatch,
        requests.ConnectionError("raw connection detail for 10.0.0.8"),
    )

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/")

    assert exc_info.value.status_code == 502
    assert exc_info.value.public_message == analyzer.FETCH_FAILED_MESSAGE
    assert "10.0.0.8" not in str(exc_info.value)
    assert session.closed


def test_analyze_site_returns_sanitized_fetch_error(monkeypatch):
    allow_public_dns(monkeypatch)
    install_session(
        monkeypatch,
        requests.ConnectionError("raw internal destination 10.0.0.8"),
    )
    monkeypatch.setattr(llm_router, "get_llm_client", lambda: object())

    with pytest.raises(HTTPException) as exc_info:
        llm_router.analyze_site(llm_router.AnalyzeRequest(url="https://public.example/"))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == analyzer.FETCH_FAILED_MESSAGE
    assert "10.0.0.8" not in str(exc_info.value.detail)


def test_analyze_site_route_is_synchronous():
    assert not inspect.iscoroutinefunction(llm_router.analyze_site)
