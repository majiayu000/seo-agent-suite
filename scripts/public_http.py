#!/usr/bin/env python3
"""Shared fail-closed public HTTP URL validation and pinned fetching."""

from __future__ import annotations

import base64
import codecs
import http.client
import ipaddress
import socket
import ssl
import urllib.parse
import urllib.request
from email.message import Message

SocketAddress = tuple[str, int] | tuple[str, int, int, int]
ResolvedEndpoint = tuple[int, int, int, str, SocketAddress]

USER_AGENT = "github-repo-seo-skill/1.0"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


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


def charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    message = Message()
    message["content-type"] = content_type
    charset = message.get_param("charset")
    if charset is None:
        return None
    if isinstance(charset, tuple):
        charset = charset[-1]
    charset = str(charset).strip().strip("'\"") or None
    if not charset:
        return None
    try:
        codecs.lookup(charset)
    except LookupError:
        return None
    return charset


def redact_proxy_url(raw: str) -> str:
    """Describe a proxy URL without username/password material."""
    proxy = urllib.parse.urlparse(raw)
    if proxy.scheme and proxy.hostname:
        port = f":{proxy.port}" if proxy.port is not None else ""
        return f"{proxy.scheme}://{proxy.hostname}{port}"
    # Authority-form values have no scheme; still strip any userinfo if present.
    if "://" not in raw and "@" in raw:
        return raw.rsplit("@", 1)[-1] or "<unparseable-proxy>"
    if "://" not in raw and raw.strip():
        return raw.strip()
    return "<unparseable-proxy>"


def _strip_userinfo_heuristic(url: str) -> str:
    """Best-effort credential strip when urlparse cannot handle the authority."""
    if "://" in url and "@" in url.split("://", 1)[1]:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://{rest.rsplit('@', 1)[-1]}"
    return url


def redact_url(url: str) -> str:
    """Return a URL with userinfo removed so credentials never reach audit output."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        # Malformed bracketed authorities raise before any guarded request path.
        return _strip_userinfo_heuristic(url)
    if parsed.username is None and parsed.password is None:
        return url
    host = parsed.hostname or ""
    try:
        if ipaddress.ip_address(host.split("%", 1)[0]).version == 6 and not host.startswith("["):
            host = f"[{host}]"
    except ValueError:
        pass
    try:
        port = parsed.port
    except ValueError:
        # Malformed ports raise on .port access; strip userinfo from the raw netloc instead.
        netloc = parsed.netloc.rsplit("@", 1)[-1] if "@" in parsed.netloc else parsed.netloc
        return urllib.parse.urlunparse(
            (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
        )
    netloc = host if port is None else f"{host}:{port}"
    return urllib.parse.urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def _parse_proxy_setting(raw: str) -> urllib.parse.ParseResult:
    """Parse a proxy env value, accepting both URL and authority (host:port) forms."""
    proxy = urllib.parse.urlparse(raw)
    if proxy.scheme in {"http", "https"} and proxy.hostname:
        return proxy
    # urllib.request.getproxies() may return authority-form values like "proxy.example:8080".
    if "://" not in raw and raw.strip():
        return urllib.parse.urlparse(f"http://{raw.strip()}")
    return proxy


def _proxy_bypass_host(parsed: urllib.parse.ParseResult) -> str:
    """Format a host key for proxy_bypass, keeping IPv6 authorities bracketed."""
    host = parsed.hostname
    if host is None:
        return ""
    bare = host.split("%", 1)[0]
    try:
        if ipaddress.ip_address(bare).version == 6 and not host.startswith("["):
            host = f"[{bare}]"
    except ValueError:
        pass
    try:
        port = parsed.port
    except ValueError:
        return host
    return host if port is None else f"{host}:{port}"


def select_proxy(parsed: urllib.parse.ParseResult) -> urllib.parse.ParseResult | None:
    """Return an HTTP proxy for the target, honoring env/system proxy settings.

    Only cleartext http:// proxies are supported: CONNECT tunnels pin the
    validated endpoint IP while preserving the original Host/SNI. TLS-wrapped
    https:// proxy endpoints are rejected here so selection matches
    request_via_proxy (which cannot open a nested TLS CONNECT path).
    """
    host = parsed.hostname
    if host is None:
        return None
    bypass_host = _proxy_bypass_host(parsed)
    try:
        if urllib.request.proxy_bypass(bypass_host):
            return None
    except OSError:
        pass
    proxies = urllib.request.getproxies()
    # Match urllib: scheme-specific first, then ALL_PROXY ("all"); never fall HTTP_PROXY onto HTTPS.
    raw = proxies.get(parsed.scheme) or proxies.get("all")
    if not raw:
        return None
    proxy = _parse_proxy_setting(raw)
    if not proxy.hostname:
        raise OSError(f"unsupported proxy URL: {redact_proxy_url(raw)}")
    if proxy.scheme == "https":
        raise OSError(
            "proxied fetches require an http:// proxy for CONNECT tunneling; "
            f"got {redact_proxy_url(raw)}"
        )
    if proxy.scheme != "http":
        raise OSError(f"unsupported proxy URL: {redact_proxy_url(raw)}")
    return proxy


def _proxy_authorization(proxy: urllib.parse.ParseResult) -> dict[str, str]:
    if proxy.username is None:
        return {}
    user = urllib.parse.unquote(proxy.username)
    password = urllib.parse.unquote(proxy.password or "")
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return {"Proxy-Authorization": f"Basic {token}"}


def _bracket_ip_literal(address: str) -> str:
    host = address.split("%", 1)[0]
    try:
        if ipaddress.ip_address(host).version == 6 and not host.startswith("["):
            return f"[{host}]"
    except ValueError:
        pass
    return host


def _ascii_hostname(hostname: str) -> str:
    """Return a Latin-1-safe hostname (IDNA for names, brackets for IPv6 literals)."""
    bare = hostname.split("%", 1)[0]
    try:
        if ipaddress.ip_address(bare).version == 6:
            return hostname if hostname.startswith("[") else f"[{bare}]"
        return bare
    except ValueError:
        pass
    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise OSError(f"invalid hostname for Host header: {exc}") from exc


def _http_host_header(parsed: urllib.parse.ParseResult, target_port: int) -> str:
    hostname = parsed.hostname
    if hostname is None:
        raise OSError("target host is missing")
    default_port = 443 if parsed.scheme == "https" else 80
    hostname = _ascii_hostname(hostname)
    if target_port == default_port:
        return hostname
    return f"{hostname}:{target_port}"


class ProxyPinnedHTTPConnection(http.client.HTTPConnection):
    """CONNECT to a validated endpoint IP via an HTTP proxy, then request with original Host."""

    def __init__(
        self,
        proxy_host: str,
        proxy_port: int,
        *,
        endpoint_ip: str,
        target_port: int,
        timeout: int,
        tunnel_headers: dict[str, str] | None = None,
    ):
        super().__init__(proxy_host, port=proxy_port, timeout=timeout)
        tunnel_host = _bracket_ip_literal(endpoint_ip)
        headers = dict(tunnel_headers or {})
        headers.setdefault("Host", f"{tunnel_host}:{target_port}")
        self.set_tunnel(tunnel_host, target_port, headers=headers)


class ProxyPinnedHTTPSConnection(http.client.HTTPSConnection):
    """CONNECT to a validated endpoint IP via an HTTP proxy, TLS with original hostname SNI."""

    def __init__(
        self,
        proxy_host: str,
        proxy_port: int,
        *,
        server_hostname: str,
        endpoint_ip: str,
        target_port: int,
        timeout: int,
        tunnel_headers: dict[str, str] | None = None,
    ):
        context = ssl.create_default_context()
        context.set_alpn_protocols(["http/1.1"])
        super().__init__(proxy_host, port=proxy_port, timeout=timeout, context=context)
        # Bracket IPv6 so CONNECT and the tunnel Host header share a clear authority form.
        tunnel_host = _bracket_ip_literal(endpoint_ip)
        headers = dict(tunnel_headers or {})
        headers.setdefault("Host", f"{tunnel_host}:{target_port}")
        self.set_tunnel(tunnel_host, target_port, headers=headers)
        self._server_hostname = server_hostname

    def connect(self) -> None:
        # Parent HTTPSConnection would SNI to the tunnel IP; pin TLS to the public hostname instead.
        http.client.HTTPConnection.connect(self)
        try:
            self.sock = self._context.wrap_socket(self.sock, server_hostname=self._server_hostname)
        except OSError:
            if self.sock is not None:
                self.sock.close()
            raise


def request_via_proxy(
    parsed: urllib.parse.ParseResult,
    path: str,
    proxy: urllib.parse.ParseResult,
    endpoints: list[ResolvedEndpoint],
    timeout: int,
    *,
    max_body_bytes: int,
) -> dict:
    """Fetch through an HTTP proxy while keeping the already-validated public target."""
    if proxy.hostname is None or parsed.hostname is None:
        raise OSError("proxy or target host is missing")
    if not endpoints:
        raise OSError("no validated endpoints available for proxied request")
    # CONNECT tunnels require an http:// proxy for both cleartext and TLS targets so the
    # absolute-form Host/authority mismatch cannot replace the original hostname.
    if proxy.scheme != "http":
        raise OSError("proxied fetches require an http:// proxy for CONNECT tunneling")
    proxy_port = proxy.port if proxy.port is not None else 80
    target_port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    auth_headers = _proxy_authorization(proxy)
    host_header = _http_host_header(parsed, target_port)
    errors: list[str] = []

    for endpoint in endpoints:
        endpoint_ip = endpoint[4][0].split("%", 1)[0]
        connection: http.client.HTTPConnection
        try:
            if parsed.scheme == "https":
                connection = ProxyPinnedHTTPSConnection(
                    proxy.hostname,
                    proxy_port,
                    server_hostname=parsed.hostname,
                    endpoint_ip=endpoint_ip,
                    target_port=target_port,
                    timeout=timeout,
                    tunnel_headers=auth_headers or None,
                )
            else:
                connection = ProxyPinnedHTTPConnection(
                    proxy.hostname,
                    proxy_port,
                    endpoint_ip=endpoint_ip,
                    target_port=target_port,
                    timeout=timeout,
                    tunnel_headers=auth_headers or None,
                )
            headers = {"User-Agent": USER_AGENT, "Host": host_header}

            try:
                connection.request("GET", path, headers=headers)
                response = connection.getresponse()
                body = response.read(max_body_bytes)
                return {
                    "http_status": response.status,
                    "content_type": response.getheader("content-type"),
                    "sample_bytes": len(body),
                    "location": response.getheader("location"),
                    "body": body,
                }
            finally:
                connection.close()
        except (OSError, http.client.HTTPException) as exc:
            errors.append(str(exc) or type(exc).__name__)

    raise OSError("; ".join(errors) or "proxied connection failed")


def request_public_url_once(url: str, timeout: int, *, max_body_bytes: int = 2048) -> dict:
    parsed, endpoints = validate_public_http_url(url)
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    path = urllib.parse.urlunparse(("", "", parsed.path or "/", parsed.params, parsed.query, ""))
    proxy = select_proxy(parsed)
    if proxy is not None:
        return request_via_proxy(
            parsed, path, proxy, endpoints, timeout, max_body_bytes=max_body_bytes
        )

    errors: list[str] = []

    for endpoint in endpoints:
        connection_class = PinnedHTTPSConnection if parsed.scheme == "https" else PinnedHTTPConnection
        connection = connection_class(parsed.hostname, port, endpoint, timeout)
        try:
            connection.request("GET", path, headers={"User-Agent": USER_AGENT})
            response = connection.getresponse()
            body = response.read(max_body_bytes)
            return {
                "http_status": response.status,
                "content_type": response.getheader("content-type"),
                "sample_bytes": len(body),
                "location": response.getheader("location"),
                "body": body,
            }
        except (OSError, http.client.HTTPException) as exc:
            errors.append(str(exc) or type(exc).__name__)
        finally:
            connection.close()

    raise OSError("; ".join(errors) or "connection failed")


def follow_public_http(
    url: str,
    timeout: int = 15,
    *,
    max_redirects: int = 5,
    max_body_bytes: int = 2048,
) -> dict:
    """Fetch a URL with pinned connect and re-validation on every redirect hop."""
    current_url = url
    for redirect_count in range(max_redirects + 1):
        safe_url = redact_url(current_url)
        try:
            response = request_public_url_once(current_url, timeout, max_body_bytes=max_body_bytes)
        except ValueError as exc:
            prefix = "redirect blocked: " if current_url != url else ""
            return {"status": "error", "url": safe_url, "reason": f"{prefix}{exc}"}
        except (OSError, http.client.HTTPException) as exc:
            return {"status": "error", "url": safe_url, "reason": str(exc) or type(exc).__name__}

        status = response["http_status"]
        if status in REDIRECT_STATUSES:
            location = response["location"]
            if not location:
                return {"status": "error", "url": safe_url, "reason": "redirect missing Location header"}
            if redirect_count == max_redirects:
                return {"status": "error", "url": safe_url, "reason": "too many redirects"}
            current_url = urllib.parse.urljoin(current_url, location)
            continue
        if not 200 <= status < 300:
            return {
                "status": "error",
                "url": safe_url,
                "http_status": status,
                "reason": f"HTTP status {status}",
            }
        return {
            "status": "ok",
            "url": safe_url,
            "http_status": status,
            "content_type": response["content_type"],
            "sample_bytes": response["sample_bytes"],
            "location": response["location"],
            "body": response["body"],
        }

    raise AssertionError("redirect loop bound is unreachable")


def http_check(url: str, timeout: int = 15) -> dict:
    result = follow_public_http(url, timeout=timeout, max_body_bytes=2048)
    if result.get("status") != "ok":
        return {key: value for key, value in result.items() if key != "body"}
    return {
        "status": "ok",
        "url": result["url"],
        "http_status": result["http_status"],
        "content_type": result["content_type"],
        "sample_bytes": result["sample_bytes"],
        "location": result["location"],
    }


def fetch_public_url(url: str, timeout: int = 20, *, max_body_bytes: int = 1_000_000) -> dict:
    """Return audit-friendly fetch result with decoded body for successful responses."""
    result = follow_public_http(url, timeout=timeout, max_body_bytes=max_body_bytes)
    if result.get("status") != "ok":
        return {key: value for key, value in result.items() if key != "body"}
    content_type = result.get("content_type")
    body = result.get("body") or b""
    charset = charset_from_content_type(content_type) or "utf-8"
    return {
        "status": "ok",
        "url": result["url"],
        "http_status": result["http_status"],
        "content_type": content_type,
        "body": body.decode(charset, errors="replace"),
    }
