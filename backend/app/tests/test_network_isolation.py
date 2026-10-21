"""Verify rejection before any real connection, independently of provider mocks."""
import asyncio
import socket
import urllib.request

import httpx
import pytest
from ddgs import DDGS
from ddgs.ddgs import DDGS as DDGSImplementation

from conftest import NetworkBlocked, install_network_guard


@pytest.mark.parametrize("constructor", [DDGS, DDGSImplementation])
def test_ddgs_proxy_and_implementation_are_both_blocked(monkeypatch, constructor):
    with monkeypatch.context() as inner:
        attempts = install_network_guard(inner)
        with pytest.raises(NetworkBlocked):
            constructor(timeout=1)
        assert len(attempts) == 1


@pytest.mark.parametrize("url", [
    "https://api.exa.ai/search", "https://api.deepseek.com/chat/completions",
    "https://openrouter.ai/api/v1/chat/completions",
])
def test_provider_http_is_blocked_without_a_request(monkeypatch, url):
    with monkeypatch.context() as inner:
        attempts = install_network_guard(inner)
        with httpx.Client(trust_env=False) as client, pytest.raises(NetworkBlocked):
            client.post(url)
        assert len(attempts) == 1


def test_async_http_is_blocked(monkeypatch):
    async def request():
        async with httpx.AsyncClient(trust_env=False) as client:
            await client.get("https://openrouter.ai/api/v1/models")
    with monkeypatch.context() as inner:
        attempts = install_network_guard(inner)
        with pytest.raises(NetworkBlocked):
            asyncio.run(request())
        assert len(attempts) == 1


def test_stdlib_dns_sockets_udp_and_native_ddgs_are_blocked(monkeypatch):
    with monkeypatch.context() as inner:
        # Fail safely even if a guard regresses or an external URL uses a local proxy.
        def unexpected_io(*args, **kwargs):
            raise AssertionError("Network guard reached low-level I/O")
        for method in ("connect", "connect_ex", "sendto"):
            inner.setattr(socket.socket, method, unexpected_io)
        attempts = install_network_guard(inner)
        for operation in (
            lambda: socket.getaddrinfo("api.exa.ai", 443),
            lambda: urllib.request.urlopen("https://example.com", timeout=1),
            lambda: DDGS(timeout=1),
        ):
            with pytest.raises(NetworkBlocked):
                operation()
        with socket.socket() as sock:
            for connect in (sock.connect, sock.connect_ex):
                with pytest.raises(NetworkBlocked):
                    connect(("203.0.113.1", 443))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            with pytest.raises(NetworkBlocked):
                sock.sendto(b"test", ("203.0.113.1", 53))
        assert len(attempts) == 6


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_external_url_through_loopback_proxy_is_blocked_before_io(monkeypatch, scheme):
    with monkeypatch.context() as inner:
        reached_io = []
        def unexpected_io(*args, **kwargs):
            reached_io.append(None)
            raise AssertionError("Proxy test reached low-level I/O")
        inner.setattr(socket, "create_connection", unexpected_io)
        inner.setattr(urllib.request, "_opener", urllib.request.build_opener(
            urllib.request.ProxyHandler({scheme: "http://127.0.0.1:9"}),
        ))
        attempts = install_network_guard(inner)
        with pytest.raises(NetworkBlocked):
            urllib.request.urlopen(f"{scheme}://example.com", timeout=1)
        assert len(attempts) == 1
        assert not reached_io


def test_mock_transport_and_loopback_dns_remain_usable():
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"offline": True}))) as client:
        assert client.get("https://api.exa.ai/search").json() == {"offline": True}
    assert socket.getaddrinfo("127.0.0.1", 8000)
