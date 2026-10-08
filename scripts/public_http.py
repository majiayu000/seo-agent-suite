#!/usr/bin/env python3
"""Shared fail-closed public HTTP URL validation and pinned fetching."""

from __future__ import annotations

import base64
import http.client
import ipaddress
import re
import socket
import ssl
import urllib.parse
import urllib.request
from email.message import Message
from datetime import datetime, timezone
from html.parser import HTMLParser

SocketAddress = tuple[str, int] | tuple[str, int, int, int]
ResolvedEndpoint = tuple[int, int, int, str, SocketAddress]

USER_AGENT = "seo-agent-suite/0.2.0 (+https://github.com/majiayu000/seo-agent-suite)"
ROBOTS_UA_TOKEN = "seo-agent-suite"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
# Politeness defaults for single-URL fetches (not a sitewide crawler).
DEFAULT_MAX_BODY_BYTES = 1_000_000
DEFAULT_TIMEOUT_SECONDS = 20


class HTTPAttemptBudgetExhausted(Exception):
    """A terminal collection limit, never a retriable transport failure."""

    def __init__(self, prior_errors: list[str] | None = None):
        super().__init__("HTTP target attempt allowance exhausted")
        self.prior_errors = list(prior_errors or [])


class HTTPAttemptBudget:
    """Invocation-local allowance for logical direct/proxy target attempts.

    A CONNECT tunnel and its target GET form one attempt. DNS, headers,
    TLS/proxy framing and requests inside other programs are not counted.
    """

    def __init__(self, max_http_attempts: int):
        if type(max_http_attempts) is not int or max_http_attempts < 0:
            raise ValueError("max_http_attempts must be a nonnegative integer")
        self.max_http_attempts = max_http_attempts
        self.attempts_used = 0

    def charge(self, prior_errors: list[str] | None = None) -> None:
        if self.attempts_used >= self.max_http_attempts:
            raise HTTPAttemptBudgetExhausted(prior_errors)
        self.attempts_used += 1


class HTTPBodyBudgetExhausted(Exception):
    """An exposed-payload collection limit, never a retriable failure."""

    def __init__(self, prior_errors: list[str] | None = None):
        super().__init__("HTTP exposed body-payload byte allowance exhausted")
        self.prior_errors = list(prior_errors or [])


class HTTPBodyBudget:
    """Count encoded payload exposed by reads, not physical network traffic.

    Socket buffering, framing, and bytes hidden by failed reads are excluded.
    """

    def __init__(self, max_http_body_bytes: int):
        if type(max_http_body_bytes) is not int or max_http_body_bytes < 0:
            raise ValueError("max_http_body_bytes must be a nonnegative integer")
        self.max_http_body_bytes = max_http_body_bytes
        self.bytes_used = 0
        self.attempts_started = 0

    @property
    def remaining(self) -> int:
        return self.max_http_body_bytes - self.bytes_used

    def require_remaining(self, prior_errors: list[str] | None = None) -> None:
        if self.remaining == 0:
            raise HTTPBodyBudgetExhausted(prior_errors)


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
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if isinstance(ip, ipaddress.IPv6Address):
            if ip.ipv4_mapped is not None:
                ip = ip.ipv4_mapped
            elif ip in ipaddress.IPv6Network("64:ff9b::/96"):
                # RFC 6052 embeds the actual IPv4 destination in the low 32 bits.
                ip = ipaddress.IPv4Address(ip.packed[-4:])
        if (
            not ip.is_global
            or ip.is_multicast
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_unspecified
            or ip.is_reserved
            or (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local)
        ):
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
        # lookup() also accepts binary transforms such as base64_codec, which
        # bytes.decode() explicitly rejects as a text encoding.
        b"test".decode(charset, errors="replace")
    except (LookupError, ValueError, TypeError, UnicodeError):
        return None
    return charset


class _HTMLCharsetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.charset: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta" or self.charset is not None:
            return
        attributes = dict(attrs)
        if attributes.get("charset"):
            self.charset = charset_from_content_type(f"text/html; charset={attributes['charset']}")
        elif (attributes.get("http-equiv") or "").lower() == "content-type":
            self.charset = charset_from_content_type(attributes.get("content"))


def charset_from_html(body: bytes) -> str | None:
    # Latin-1 preserves the ASCII markup while avoiding guesses about body text.
    parser = _HTMLCharsetParser()
    parser.feed(body.decode("latin-1"))
    return parser.charset


def _read_success_body(response: http.client.HTTPResponse, max_body_bytes: int) -> bytes:
    # Redirect/error evidence comes from headers; their bodies are not consumed.
    if not 200 <= response.status < 300:
        return b""
    expected_length = getattr(response, "length", None)
    body = response.read(max_body_bytes)
    # HTTPResponse.read(amount) does not itself reject an early EOF on a
    # Content-Length response. Only require the bytes needed for this sample.
    if isinstance(expected_length, int) and expected_length >= 0:
        required = min(expected_length, max_body_bytes)
        if len(body) < required:
            raise http.client.IncompleteRead(body, required - len(body))
    return body


def _read_body_evidence(response: http.client.HTTPResponse, max_body_bytes: int,
                        body_budget: HTTPBodyBudget | None) -> dict:
    if body_budget is None:
        return {"body": _read_success_body(response, max_body_bytes)}
    # Preserve the header-only treatment of redirect/error responses.
    if not 200 <= response.status < 300:
        return {"body": b""}
    expected = getattr(response, "length", None)
    known_length = type(expected) is int and expected >= 0
    amount = min(max_body_bytes, body_budget.remaining)
    try:
        body = response.read(amount)
    except http.client.IncompleteRead as exc:
        # Only exposed partial payload can be counted; hidden failed-read bytes
        # are not observable through this API. Never count this partial twice.
        body_budget.bytes_used += len(exc.partial)
        raise
    body_budget.bytes_used += len(body)
    if known_length and len(body) < min(expected, amount):
        raise http.client.IncompleteRead(body, min(expected, amount) - len(body))
    complete = len(body) == expected if known_length else len(body) < amount
    if not complete and body_budget.remaining == 0:
        return {"body": body, "reason_code": "http_body_budget_exhausted",
                "reason": "HTTP exposed body-payload byte allowance reached; response completion is unverified"}
    return {"body": body}


def _response_header_values(response: http.client.HTTPResponse, name: str) -> list[str]:
    if response.getheader(name) is None:
        return []
    values = [value for key, value in response.getheaders() if key.lower() == name]
    if name == "link":
        values = [
            re.sub(r"<([^>]*)>", lambda match: f"<{redact_url(match.group(1))}>", value)
            for value in values
        ]
    return values


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
    budget: HTTPAttemptBudget | None = None,
    body_budget: HTTPBodyBudget | None = None,
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
        if body_budget is not None:
            body_budget.require_remaining(errors)
        if budget is not None:
            budget.charge(errors)
        if body_budget is not None:
            body_budget.attempts_started += 1
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
            headers = default_request_headers(host=host_header)

            try:
                connection.request("GET", path, headers=headers)
                response = connection.getresponse()
                body_evidence = _read_body_evidence(response, max_body_bytes, body_budget)
                body = body_evidence["body"]
                return {
                    "http_status": response.status,
                    "content_type": response.getheader("content-type"),
                    "content_encoding": response.getheader("content-encoding"),
                    "sample_bytes": len(body),
                    "location": response.getheader("location"),
                    "x_robots_tag": _response_header_values(response, "x-robots-tag"),
                    "link_headers": _response_header_values(response, "link"),
                    **body_evidence,
                }
            finally:
                connection.close()
        except (OSError, http.client.HTTPException) as exc:
            errors.append(str(exc) or type(exc).__name__)

    raise OSError("; ".join(errors) or "proxied connection failed")


def request_public_url_once(
    url: str, timeout: int, *, max_body_bytes: int = 2048,
    budget: HTTPAttemptBudget | None = None,
    body_budget: HTTPBodyBudget | None = None,
) -> dict:
    if budget is not None and budget.attempts_used >= budget.max_http_attempts:
        raise HTTPAttemptBudgetExhausted()
    if body_budget is not None:
        body_budget.require_remaining()
    parsed, endpoints = validate_public_http_url(url)
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    path = urllib.parse.urlunparse(("", "", parsed.path or "/", parsed.params, parsed.query, ""))
    path = urllib.parse.quote(path, safe="/%:;?@&=+$,!~*'()[]")
    proxy = select_proxy(parsed)
    if proxy is not None:
        return request_via_proxy(
            parsed, path, proxy, endpoints, timeout, max_body_bytes=max_body_bytes,
            **({"budget": budget} if budget is not None else {}),
            **({"body_budget": body_budget} if body_budget is not None else {}),
        )

    errors: list[str] = []

    for endpoint in endpoints:
        if body_budget is not None:
            body_budget.require_remaining(errors)
        if budget is not None:
            budget.charge(errors)
        if body_budget is not None:
            body_budget.attempts_started += 1
        connection_class = PinnedHTTPSConnection if parsed.scheme == "https" else PinnedHTTPConnection
        connection = connection_class(parsed.hostname, port, endpoint, timeout)
        try:
            connection.request("GET", path, headers=default_request_headers())
            response = connection.getresponse()
            body_evidence = _read_body_evidence(response, max_body_bytes, body_budget)
            body = body_evidence["body"]
            return {
                "http_status": response.status,
                "content_type": response.getheader("content-type"),
                "content_encoding": response.getheader("content-encoding"),
                "sample_bytes": len(body),
                "location": response.getheader("location"),
                "x_robots_tag": _response_header_values(response, "x-robots-tag"),
                "link_headers": _response_header_values(response, "link"),
                **body_evidence,
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
    budget: HTTPAttemptBudget | None = None,
    body_budget: HTTPBodyBudget | None = None,
) -> dict:
    """Fetch a URL with pinned connect and re-validation on every redirect hop."""
    current_url = url
    evidence = {
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "redirects": [],
        "x_robots_tag": [],
        "link_headers": [],
    }
    for redirect_count in range(max_redirects + 1):
        safe_url = redact_url(current_url)
        try:
            response = request_public_url_once(
                current_url, timeout, max_body_bytes=max_body_bytes,
                **({"budget": budget} if budget is not None else {}),
                **({"body_budget": body_budget} if body_budget is not None else {}),
            )
        except (HTTPAttemptBudgetExhausted, HTTPBodyBudgetExhausted) as exc:
            result = {**evidence, "status": "unavailable", "url": safe_url,
                      "reason": str(exc), "reason_code": "http_body_budget_exhausted" if isinstance(exc, HTTPBodyBudgetExhausted) else "http_attempt_budget_exhausted"}
            if exc.prior_errors:
                result["endpoint_errors"] = [
                    re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>]+",
                           lambda match: redact_url(match.group()), error)
                    for error in exc.prior_errors
                ]
            return result
        except ValueError as exc:
            prefix = "redirect blocked: " if current_url != url else ""
            return {**evidence, "status": "error", "url": safe_url, "reason": f"{prefix}{exc}"}
        except (OSError, http.client.HTTPException) as exc:
            return {**evidence, "status": "error", "url": safe_url, "reason": str(exc) or type(exc).__name__}

        status = response["http_status"]
        evidence["x_robots_tag"] = response.get("x_robots_tag", [])
        evidence["link_headers"] = response.get("link_headers", [])
        if status in REDIRECT_STATUSES:
            location = response["location"]
            evidence["redirects"].append(
                {"url": safe_url, "status": status, "location": redact_url(location) if location else location}
            )
            if not location:
                return {**evidence, "status": "error", "url": safe_url, "reason": "redirect missing Location header"}
            if redirect_count == max_redirects:
                return {**evidence, "status": "error", "url": safe_url, "reason": "too many redirects"}
            try:
                current_url = urllib.parse.urljoin(current_url, location)
            except ValueError as exc:
                return {**evidence, "status": "error", "url": safe_url, "reason": f"redirect blocked: {exc}"}
            continue
        if not 200 <= status < 300:
            return {
                **evidence,
                "status": "error",
                "url": safe_url,
                "http_status": status,
                "reason": f"HTTP status {status}",
            }
        return {
            **evidence,
            "status": "ok",
            "url": safe_url,
            "http_status": status,
            "content_type": response["content_type"],
            "content_encoding": response.get("content_encoding"),
            "sample_bytes": response["sample_bytes"],
            "location": redact_url(response["location"]) if response["location"] else response["location"],
            "body": response["body"],
            **({key: response[key] for key in ("reason_code", "reason")} if response.get("reason_code") == "http_body_budget_exhausted" else {}),
        }

    raise AssertionError("redirect loop bound is unreachable")


def http_check(url: str, timeout: int = 15, *, budget: HTTPAttemptBudget | None = None) -> dict:
    result = follow_public_http(url, timeout=timeout, max_body_bytes=2048,
                                **({"budget": budget} if budget is not None else {}))
    return {key: value for key, value in result.items() if key != "body"}


def fetch_public_url(
    url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS, *, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    budget: HTTPAttemptBudget | None = None,
    body_budget: HTTPBodyBudget | None = None,
) -> dict:
    """Return audit-friendly fetch result with decoded body for successful responses."""
    # Read one extra byte to distinguish a bounded sample from a response at EOF.
    result = follow_public_http(url, timeout=timeout, max_body_bytes=max_body_bytes + 1,
                                **({"budget": budget} if budget is not None else {}),
                                **({"body_budget": body_budget} if body_budget is not None else {}))
    if result.get("status") != "ok":
        return {key: value for key, value in result.items() if key != "body"}
    content_type = result.get("content_type")
    body = result.get("body") or b""
    body_truncated = len(body) > max_body_bytes or result.get("reason_code") == "http_body_budget_exhausted"
    body = body[:max_body_bytes]
    charset = charset_from_content_type(content_type)
    if charset is None and (not content_type or content_type.split(";", 1)[0].strip().lower() in {"text/html", "application/xhtml+xml"}):
        charset = charset_from_html(body)
    charset = charset or "utf-8"
    try:
        decoded_body = body.decode(charset, errors="replace")
    except (LookupError, ValueError, TypeError, UnicodeError):
        decoded_body = body.decode("utf-8", errors="replace")
    return {
        "status": "ok",
        "url": result["url"],
        "http_status": result["http_status"],
        "content_type": content_type,
        "content_encoding": result.get("content_encoding"),
        "body": decoded_body,
        "body_truncated": body_truncated,
        "collected_at": result["collected_at"],
        "redirects": result["redirects"],
        "x_robots_tag": result["x_robots_tag"],
        "link_headers": result["link_headers"],
        **({key: result[key] for key in ("reason_code", "reason")} if result.get("reason_code") == "http_body_budget_exhausted" else {}),
    }


def robots_path_allowed(robots_body: str, path: str, *, user_agent: str = USER_AGENT) -> bool:
    """Return whether robots.txt allows fetching path for our user-agent.

    Implements a small, fail-open subset of the robots exclusion protocol:
    empty/malformed input allows; longest matching Allow/Disallow for the
    matching User-agent group wins. This is a safety helper for callers — it
    does not turn public_http into a sitewide crawler.
    """
    if not robots_body or not path:
        return True
    if not path.startswith("/"):
        path = "/" + path

    token = (user_agent or USER_AGENT).split("/")[0].strip().lower() or ROBOTS_UA_TOKEN
    groups: list[tuple[list[str], list[tuple[str, bool]]]] = []
    current_uas: list[str] = []
    current_rules: list[tuple[str, bool]] = []

    def flush() -> None:
        nonlocal current_uas, current_rules
        if current_uas:
            groups.append((current_uas, current_rules))
        current_uas, current_rules = [], []

    for raw in robots_body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if current_rules:
                flush()
            current_uas.append(value.lower())
        elif key in {"allow", "disallow"}:
            if not current_uas:
                current_uas = ["*"]
            current_rules.append((value, key == "allow"))
    flush()

    matched_rules: list[tuple[str, bool]] | None = None
    starred: list[tuple[str, bool]] | None = None
    for uas, rules in groups:
        if token in uas or any(token.startswith(ua) for ua in uas if ua != "*"):
            matched_rules = rules
            break
        if "*" in uas:
            starred = rules
    rules = matched_rules if matched_rules is not None else (starred or [])
    best: tuple[int, bool] | None = None  # (prefix_len, allowed)
    for rule_path, allowed in rules:
        if rule_path == "":
            # Empty Disallow means allow all; empty Allow is ignored by common practice.
            if not allowed:
                candidate = (0, True)
            else:
                continue
        elif path.startswith(rule_path):
            candidate = (len(rule_path), allowed)
        else:
            continue
        if best is None or candidate[0] > best[0]:
            best = candidate
    return True if best is None else best[1]


def default_request_headers(*, host: str | None = None) -> dict[str, str]:
    """Identifying UA for polite public fetches."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if host:
        headers["Host"] = host
    return headers
