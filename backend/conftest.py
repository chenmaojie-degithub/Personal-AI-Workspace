"""Default pytest isolation: no provider credentials, external network, or model downloads."""
import ipaddress
import http.client
import socket
from urllib.parse import urlsplit

import httpx
import pytest
from ddgs.ddgs import DDGS  # Patch the implementation, not its lazy-loading proxy.


class NetworkBlocked(AssertionError):
    pass


def install_network_guard(monkeypatch):
    """Return an attempt counter; never retain URLs, headers, keys, or payloads."""
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append(None)
        raise NetworkBlocked("Live external network forbidden in tests; supply a mock")

    async def blocked_async(*args, **kwargs):
        blocked()

    def local(host):
        if host in (None, "localhost", b"localhost"):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def guarded_connect(original):
        def connect(sock, address):
            # AF_UNIX addresses and event-loop loopback sockets stay local.
            if isinstance(address, tuple) and not local(address[0]):
                blocked()
            return original(sock, address)
        return connect

    original_dns = socket.getaddrinfo
    def dns(host, *args, **kwargs):
        if not local(host):
            blocked()
        return original_dns(host, *args, **kwargs)

    original_sendto = socket.socket.sendto
    def sendto(sock, *args):
        address = args[-1]
        if isinstance(address, tuple) and not local(address[0]):
            blocked()
        return original_sendto(sock, *args)

    original_putrequest = http.client.HTTPConnection.putrequest
    def putrequest(connection, method, url, *args, **kwargs):
        # A loopback proxy is local, but its HTTP URL / CONNECT target may not be.
        target = urlsplit(url).hostname or connection._tunnel_host or connection.host
        if not local(target):
            blocked()
        return original_putrequest(connection, method, url, *args, **kwargs)

    # Covers OpenAI SDK (DeepSeek/OpenRouter/embeddings) and Exa. MockTransport
    # and TestClient's ASGI transport deliberately remain usable.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked_async)
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect(socket.socket.connect_ex))
    monkeypatch.setattr(socket.socket, "sendto", sendto)
    monkeypatch.setattr(http.client.HTTPConnection, "putrequest", putrequest)
    # DDGS can use native transports that bypass Python socket/HTTPX hooks.
    # Provider tests replace the DDGS symbol with their own mock instead.
    monkeypatch.setattr(DDGS, "__init__", blocked)
    return attempts


@pytest.fixture(autouse=True)
def isolated_tests(monkeypatch):
    from app.core.config import settings
    from app.rag import embeddings

    # Memory integration tests explicitly opt in to their own temporary sidecar.
    monkeypatch.setattr(settings, "memory_enabled", False)

    for name in ("exa_api_key", "deepseek_api_key", "openrouter_api_key", "openai_api_key", "openai_embedding_api_key"):
        monkeypatch.setattr(settings, name, None)
        monkeypatch.setenv(name.upper(), "")

    class OfflineEmbedding:
        def __init__(self, *args, **kwargs):
            pass

        def embed(self, texts):
            return [[float(len(text)), 1.0, 0.0] for text in texts]

    monkeypatch.setattr(embeddings, "FastEmbedEmbeddingProvider", OfflineEmbedding)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    attempts = install_network_guard(monkeypatch)
    yield
    assert not attempts, "Test attempted live network, even if application code caught the error; supply a mock"
