#!/usr/bin/env python3
"""Public-only HTTP helpers with DNS pinning and per-redirect revalidation."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.parse

SocketAddress = tuple[str, int] | tuple[str, int, int, int]
ResolvedEndpoint = tuple[int, int, int, str, SocketAddress]


def validate_public_http_url(url: str) -> tuple[urllib.parse.ParseResult, list[ResolvedEndpoint]]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("unsupported URL scheme")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not allowed")
    try:
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("invalid URL port") from exc
    if port == 0:
        raise ValueError("invalid URL port")
    try:
        endpoints = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"hostname resolution failed: {exc}") from exc
    if not endpoints:
        raise ValueError("hostname resolution returned no addresses")
    addresses = {item[4][0].split("%", 1)[0] for item in endpoints}
    blocked = sorted(address for address in addresses if not ipaddress.ip_address(address).is_global)
    if blocked:
        raise ValueError("URL resolves to a non-public address")
    return parsed, endpoints


def connect_endpoint(endpoint: ResolvedEndpoint, timeout: int) -> socket.socket:
    family, socktype, proto, _canonname, sockaddr = endpoint
    sock = socket.socket(family, socktype, proto)
    try:
        sock.settimeout(timeout)
        sock.connect(sockaddr)
    except OSError:
        sock.close()
        raise
    return sock


class PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, endpoint: ResolvedEndpoint, timeout: int):
        super().__init__(host, port=port, timeout=timeout)
        self._endpoint = endpoint

    def connect(self) -> None:
        self.sock = connect_endpoint(self._endpoint, self.timeout)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, endpoint: ResolvedEndpoint, timeout: int):
        context = ssl.create_default_context()
        context.set_alpn_protocols(["http/1.1"])
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._endpoint = endpoint
        self._verified_context = context

    def connect(self) -> None:
        raw_socket = connect_endpoint(self._endpoint, self.timeout)
        try:
            self.sock = self._verified_context.wrap_socket(raw_socket, server_hostname=self.host)
        except OSError:
            raw_socket.close()
            raise


def request_public_url_once(url: str, timeout: int, *, max_body: int = 2048) -> dict:
    parsed, endpoints = validate_public_http_url(url)
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    path = urllib.parse.urlunparse(("", "", parsed.path or "/", "", parsed.query, ""))
    errors: list[str] = []

    for endpoint in endpoints:
        connection_class = PinnedHTTPSConnection if parsed.scheme == "https" else PinnedHTTPConnection
        connection = connection_class(parsed.hostname, port, endpoint, timeout)
        try:
            connection.request("GET", path, headers={"User-Agent": "github-repo-seo-skill/1.0"})
            response = connection.getresponse()
            body = response.read(max_body)
            return {
                "http_status": response.status,
                "content_type": response.getheader("content-type"),
                "body": body,
                "sample_bytes": len(body),
                "location": response.getheader("location"),
            }
        except (OSError, http.client.HTTPException) as exc:
            errors.append(str(exc) or type(exc).__name__)
        finally:
            connection.close()

    raise OSError("; ".join(errors) or "connection failed")


def fetch_public_http(
    url: str,
    timeout: int = 20,
    *,
    max_body: int = 2048,
    max_redirects: int = 5,
) -> dict:
    """GET a public URL with fail-closed private-target and redirect checks."""
    current_url = url
    for redirect_count in range(max_redirects + 1):
        try:
            response = request_public_url_once(current_url, timeout, max_body=max_body)
        except ValueError as exc:
            prefix = "redirect blocked: " if current_url != url else ""
            return {"status": "error", "url": current_url, "reason": f"{prefix}{exc}"}
        except (OSError, http.client.HTTPException) as exc:
            return {"status": "error", "url": current_url, "reason": str(exc) or type(exc).__name__}

        status = response["http_status"]
        if status in {301, 302, 303, 307, 308}:
            location = response["location"]
            if not location:
                return {"status": "error", "url": current_url, "reason": "redirect missing Location header"}
            if redirect_count == max_redirects:
                return {"status": "error", "url": current_url, "reason": "too many redirects"}
            current_url = urllib.parse.urljoin(current_url, location)
            continue
        if status >= 400:
            return {
                "status": "error",
                "url": current_url,
                "http_status": status,
                "reason": f"HTTP status {status}",
            }
        return {"status": "ok", "url": current_url, **response}

    raise AssertionError("redirect loop bound is unreachable")


def http_check(url: str, timeout: int = 15) -> dict:
    result = fetch_public_http(url, timeout=timeout, max_body=2048)
    if "body" in result:
        return {key: value for key, value in result.items() if key != "body"}
    return result


def charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip().strip('"') or None
    return None
