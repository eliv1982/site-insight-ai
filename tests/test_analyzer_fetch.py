from __future__ import annotations

import gzip
import inspect
import ipaddress
import socket

import pytest
import requests
from fastapi import HTTPException
from urllib3.exceptions import ProtocolError, ReadTimeoutError

from app.routers import llm as llm_router
from app.services import analyzer


PUBLIC_IPV4 = ipaddress.ip_address("93.184.216.34")
PUBLIC_IPV6 = ipaddress.ip_address("2606:4700:4700::1111")


class FakeRaw:
    def __init__(self, chunks: tuple[bytes | BaseException, ...]) -> None:
        self.chunks = chunks
        self.stream_calls: list[tuple[int, bool | None]] = []

    def stream(self, amount: int, decode_content: bool | None = None):
        self.stream_calls.append((amount, decode_content))
        assert amount == analyzer.DOWNLOAD_CHUNK_SIZE
        assert decode_content is False
        for chunk in self.chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        chunks: tuple[bytes | BaseException, ...] = (),
        encoding: str | None = "utf-8",
    ) -> None:
        self.status_code = status_code
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})
        self.chunks = chunks
        self.raw = FakeRaw(chunks)
        self.encoding = encoding
        self.closed = False
        self.iterated = False

    def iter_content(self, chunk_size: int):
        self.iterated = True
        raise AssertionError(
            f"automatic decoding via iter_content({chunk_size}) is forbidden"
        )

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


def gzip_response(
    body: bytes,
    *,
    content_encoding: str = "gzip",
    content_type: str = "text/html; charset=utf-8",
    encoding: str | None = "utf-8",
) -> FakeResponse:
    return FakeResponse(
        headers={
            "Content-Type": content_type,
            "Content-Encoding": content_encoding,
        },
        chunks=(gzip.compress(body),),
        encoding=encoding,
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
    assert response.raw.stream_calls == []
    assert response.closed and session.closed


def test_identity_content_length_at_limit_is_not_rejected_early(monkeypatch):
    allow_public_dns(monkeypatch)
    response = FakeResponse(
        headers={
            "Content-Type": "text/html",
            "Content-Length": str(analyzer.MAX_RESPONSE_BYTES),
        },
        chunks=(b"<html>identity boundary</html>",),
    )
    install_session(monkeypatch, response)

    assert analyzer.fetch_html("https://public.example/") == (
        "<html>identity boundary</html>"
    )
    assert response.raw.stream_calls == [(analyzer.DOWNLOAD_CHUNK_SIZE, False)]


def test_gzip_content_length_at_limit_is_not_rejected_early(monkeypatch):
    allow_public_dns(monkeypatch)
    body = b"<html>gzip boundary</html>"
    response = FakeResponse(
        headers={
            "Content-Type": "text/html",
            "Content-Encoding": "gzip",
            "Content-Length": str(analyzer.MAX_COMPRESSED_RESPONSE_BYTES),
        },
        chunks=(gzip.compress(body),),
    )
    install_session(monkeypatch, response)

    assert analyzer.fetch_html("https://public.example/").encode() == body
    assert response.raw.stream_calls == [(analyzer.DOWNLOAD_CHUNK_SIZE, False)]


def test_identity_body_at_limit_is_accepted(monkeypatch):
    allow_public_dns(monkeypatch)
    body = b"x" * analyzer.MAX_RESPONSE_BYTES
    response = FakeResponse(
        headers={"Content-Type": "text/html"},
        chunks=(body,),
    )
    install_session(monkeypatch, response)

    assert analyzer.fetch_html("https://public.example/") == body.decode()
    assert response.raw.stream_calls == [(analyzer.DOWNLOAD_CHUNK_SIZE, False)]
    assert not response.iterated


def test_identity_body_over_limit_is_rejected(monkeypatch):
    allow_public_dns(monkeypatch)
    response = FakeResponse(
        headers={"Content-Type": "text/html"},
        chunks=(b"12345", b"678901"),
    )
    install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/", maximum_bytes=10)

    assert exc_info.value.status_code == 413


@pytest.mark.parametrize("content_length", [None, "not-a-number"])
def test_missing_or_invalid_content_length_still_uses_stream_limit(
    monkeypatch,
    content_length,
):
    allow_public_dns(monkeypatch)
    headers = {"Content-Type": "text/html"}
    if content_length is not None:
        headers["Content-Length"] = content_length
    response = FakeResponse(headers=headers, chunks=(b"123456",))
    install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/", maximum_bytes=5)

    assert exc_info.value.status_code == 413
    assert response.raw.stream_calls == [(analyzer.DOWNLOAD_CHUNK_SIZE, False)]


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
    assert response.raw.stream_calls == [(analyzer.DOWNLOAD_CHUNK_SIZE, False)]
    assert not response.iterated


@pytest.mark.parametrize(
    "content_encoding",
    [
        "br",
        "deflate",
        "compress",
        "x-gzip",
        "unknown",
        "gzip, br",
        "gzip, identity",
        "gzip, gzip",
    ],
)
def test_unsupported_content_encoding_is_rejected_before_streaming(
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
    assert response.raw.stream_calls == []
    assert response.closed and session.closed


@pytest.mark.parametrize("content_encoding", ["gzip", "  GZip\t"])
def test_valid_gzip_html_is_decoded_from_raw_stream(monkeypatch, content_encoding):
    allow_public_dns(monkeypatch)
    body = b"<html><body>gzip works</body></html>"
    response = gzip_response(body, content_encoding=content_encoding)
    install_session(monkeypatch, response)

    html = analyzer.fetch_html("https://public.example/")

    assert html.encode("utf-8") == body
    assert response.raw.stream_calls == [(analyzer.DOWNLOAD_CHUNK_SIZE, False)]
    assert not response.iterated


def test_valid_gzip_is_decoded_across_multiple_raw_chunks(monkeypatch):
    allow_public_dns(monkeypatch)
    body = b"<html><body>split gzip stream</body></html>"
    compressed = gzip.compress(body)
    response = FakeResponse(
        headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
        chunks=tuple(compressed[index : index + 3] for index in range(0, len(compressed), 3)),
    )
    install_session(monkeypatch, response)

    assert analyzer.fetch_html("https://public.example/").encode() == body


def test_gzip_charset_handling_matches_identity(monkeypatch):
    allow_public_dns(monkeypatch)
    body = "<html><body>Привет</body></html>".encode("cp1251")
    response = gzip_response(
        body,
        content_type="text/html; charset=windows-1251",
        encoding="cp1251",
    )
    install_session(monkeypatch, response)

    html = analyzer.fetch_html("https://public.example/")

    assert html.encode("cp1251") == body
    assert "Привет" in html


def test_gzip_decoded_body_at_limit_is_accepted_with_positive_output_bounds(
    monkeypatch,
):
    allow_public_dns(monkeypatch)
    body = b"x" * analyzer.MAX_RESPONSE_BYTES
    response = gzip_response(body)
    real_decompressobj = analyzer.zlib.decompressobj
    output_limits = []

    class OutputLimitRecorder:
        def __init__(self, wbits):
            self._wrapped = real_decompressobj(wbits)

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        def decompress(self, data, max_length):
            output_limits.append(max_length)
            return self._wrapped.decompress(data, max_length)

    monkeypatch.setattr(analyzer.zlib, "decompressobj", OutputLimitRecorder)
    install_session(monkeypatch, response)

    assert analyzer.fetch_html("https://public.example/") == body.decode()
    assert output_limits
    assert all(1 <= limit <= analyzer.DOWNLOAD_CHUNK_SIZE for limit in output_limits)


def test_gzip_bomb_over_decoded_limit_is_rejected(monkeypatch):
    allow_public_dns(monkeypatch)
    body = b"x" * (analyzer.MAX_RESPONSE_BYTES + 1)
    compressed = gzip.compress(body)
    assert len(compressed) < analyzer.MAX_COMPRESSED_RESPONSE_BYTES
    response = FakeResponse(
        headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
        chunks=(compressed,),
    )
    install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/")

    assert exc_info.value.status_code == 413
    assert exc_info.value.public_message == analyzer.RESPONSE_TOO_LARGE_MESSAGE


def test_gzip_compressed_limit_is_checked_before_decompression(monkeypatch):
    allow_public_dns(monkeypatch)
    compressed = gzip.compress(b"<html>small decoded body</html>")
    monkeypatch.setattr(analyzer, "MAX_COMPRESSED_RESPONSE_BYTES", len(compressed) - 1)

    class MustNotDecompress:
        eof = False
        unused_data = b""
        unconsumed_tail = b""

        def decompress(self, _data, _max_length):
            pytest.fail("compressed over-limit data reached zlib")

    monkeypatch.setattr(
        analyzer.zlib,
        "decompressobj",
        lambda _wbits: MustNotDecompress(),
    )
    response = FakeResponse(
        headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
        chunks=(compressed,),
    )
    install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/")

    assert exc_info.value.status_code == 413


def test_gzip_body_at_compressed_limit_is_accepted(monkeypatch):
    allow_public_dns(monkeypatch)
    body = b"<html>compressed boundary</html>"
    compressed = gzip.compress(body)
    monkeypatch.setattr(analyzer, "MAX_COMPRESSED_RESPONSE_BYTES", len(compressed))
    response = FakeResponse(
        headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
        chunks=(compressed,),
    )
    install_session(monkeypatch, response)

    assert analyzer.fetch_html("https://public.example/").encode() == body


def test_gzip_content_length_uses_compressed_limit(monkeypatch):
    allow_public_dns(monkeypatch)
    monkeypatch.setattr(analyzer, "MAX_COMPRESSED_RESPONSE_BYTES", 10)
    response = FakeResponse(
        headers={
            "Content-Type": "text/html",
            "Content-Encoding": "gzip",
            "Content-Length": "11",
        },
        chunks=(gzip.compress(b"ok"),),
    )
    install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/")

    assert exc_info.value.status_code == 413
    assert response.raw.stream_calls == []


def _corrupt_gzip(body: bytes) -> bytes:
    compressed = bytearray(gzip.compress(body))
    compressed[-1] ^= 0xFF
    return bytes(compressed)


@pytest.mark.parametrize(
    "compressed",
    [
        pytest.param(b"not a gzip stream", id="malformed"),
        pytest.param(_corrupt_gzip(b"<html>checksum</html>"), id="corrupt-checksum"),
        pytest.param(gzip.compress(b"<html>truncated</html>")[:-8], id="truncated"),
        pytest.param(
            gzip.compress(b"<html>first</html>")
            + gzip.compress(b"<html>second</html>"),
            id="concatenated-members",
        ),
        pytest.param(
            gzip.compress(b"<html>first</html>") + b"trailing garbage",
            id="trailing-garbage",
        ),
    ],
)
def test_invalid_gzip_is_sanitized(monkeypatch, compressed):
    allow_public_dns(monkeypatch)
    response = FakeResponse(
        headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
        chunks=(compressed,),
    )
    install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/")

    assert exc_info.value.status_code == 502
    assert exc_info.value.public_message == analyzer.FETCH_FAILED_MESSAGE
    assert str(exc_info.value) == analyzer.FETCH_FAILED_MESSAGE


def test_gzip_rejects_a_second_member_in_a_later_raw_chunk(monkeypatch):
    allow_public_dns(monkeypatch)
    response = FakeResponse(
        headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
        chunks=(gzip.compress(b"first"), gzip.compress(b"second")),
    )
    install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/")

    assert exc_info.value.status_code == 502
    assert exc_info.value.public_message == analyzer.FETCH_FAILED_MESSAGE


def test_gzip_reader_never_calls_unbounded_flush(monkeypatch):
    allow_public_dns(monkeypatch)
    real_decompressobj = analyzer.zlib.decompressobj

    class FlushGuard:
        def __init__(self, wbits):
            self._wrapped = real_decompressobj(wbits)

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        def decompress(self, data, max_length):
            return self._wrapped.decompress(data, max_length)

        def flush(self, *_args, **_kwargs):
            pytest.fail("gzip reader called flush()")

    monkeypatch.setattr(analyzer.zlib, "decompressobj", FlushGuard)
    response = gzip_response(b"<html>bounded</html>")
    install_session(monkeypatch, response)

    assert analyzer.fetch_html("https://public.example/") == "<html>bounded</html>"


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


def test_request_timeout_maps_to_504(monkeypatch):
    allow_public_dns(monkeypatch)
    install_session(monkeypatch, requests.Timeout("raw timeout detail"))

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/")

    assert exc_info.value.status_code == 504
    assert exc_info.value.public_message == analyzer.FETCH_TIMEOUT_MESSAGE
    assert "raw timeout detail" not in str(exc_info.value)


def test_raw_stream_timeout_maps_to_504(monkeypatch):
    allow_public_dns(monkeypatch)
    response = FakeResponse(
        headers={"Content-Type": "text/html"},
        chunks=(ReadTimeoutError(None, "https://public.example/", "raw detail"),),
    )
    install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/")

    assert exc_info.value.status_code == 504
    assert exc_info.value.public_message == analyzer.FETCH_TIMEOUT_MESSAGE
    assert "raw detail" not in str(exc_info.value)


def test_raw_protocol_failure_is_sanitized(monkeypatch):
    allow_public_dns(monkeypatch)
    response = FakeResponse(
        headers={"Content-Type": "text/html"},
        chunks=(ProtocolError("raw protocol detail"),),
    )
    install_session(monkeypatch, response)

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.fetch_html("https://public.example/")

    assert exc_info.value.status_code == 502
    assert exc_info.value.public_message == analyzer.FETCH_FAILED_MESSAGE
    assert "raw protocol detail" not in str(exc_info.value)


def test_gzip_failure_does_not_call_llm(monkeypatch):
    allow_public_dns(monkeypatch)
    response = FakeResponse(
        headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
        chunks=(b"malformed gzip",),
    )
    install_session(monkeypatch, response)

    class LLMCallGuard:
        def chat_json(self, *_args, **_kwargs):
            pytest.fail("LLM call reached after gzip failure")

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.run_site_analysis("https://public.example/", LLMCallGuard())

    assert exc_info.value.status_code == 502
    assert exc_info.value.public_message == analyzer.FETCH_FAILED_MESSAGE


def test_empty_gzip_failure_does_not_call_llm(monkeypatch):
    allow_public_dns(monkeypatch)
    response = FakeResponse(
        headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
        chunks=(),
    )
    install_session(monkeypatch, response)

    class LLMCallGuard:
        def chat_json(self, *_args, **_kwargs):
            pytest.fail("LLM call reached after empty gzip failure")

    with pytest.raises(analyzer.SiteFetchError) as exc_info:
        analyzer.run_site_analysis("https://public.example/", LLMCallGuard())

    assert exc_info.value.status_code == 502
    assert exc_info.value.public_message == analyzer.FETCH_FAILED_MESSAGE


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
