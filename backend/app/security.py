import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import httpx

from .adapters import adapter_for_url
from .config import settings

ROBOTS_TTL_SECONDS = 1800
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
DEFAULT_REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
    "sec-ch-ua": '"Chromium";v="130", "Google Chrome";v="130"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "upgrade-insecure-requests": "1",
}


@dataclass(frozen=True)
class BoundedResponse:
    status_code: int
    content_type: str | None
    body: bytes
    elapsed_ms: int

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class RobotsRule:
    path: str
    allow: bool


@dataclass(frozen=True)
class RobotsGroup:
    agents: tuple[str, ...]
    rules: tuple[RobotsRule, ...]


class AccessCheckError(ValueError):
    def __init__(self, message: str, access_status: str, http_status: int | None = None,
                 content_type: str | None = None, elapsed_ms: int | None = None):
        super().__init__(message)
        self.access_status = access_status
        self.http_status = http_status
        self.content_type = content_type
        self.elapsed_ms = elapsed_ms


class RobotsPolicy:
    def __init__(self, groups: list[RobotsGroup], sitemaps: list[str], http_status: int = 200,
                 content_type: str | None = None, elapsed_ms: int = 0):
        self.groups = groups
        self._sitemaps = sitemaps
        self.http_status = http_status
        self.content_type = content_type
        self.elapsed_ms = elapsed_ms

    @classmethod
    def parse(cls, text: str, http_status: int = 200, content_type: str | None = None,
              elapsed_ms: int = 0) -> "RobotsPolicy":
        groups: list[RobotsGroup] = []
        sitemaps: list[str] = []
        agents: list[str] = []
        rules: list[RobotsRule] = []

        def finish_group():
            nonlocal agents, rules
            if agents:
                groups.append(RobotsGroup(tuple(agents), tuple(rules)))
            agents, rules = [], []

        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            name, value = (part.strip() for part in line.split(":", 1))
            name, value = name.lower(), value.strip()
            if name == "user-agent":
                if rules:
                    finish_group()
                if value:
                    agents.append(value.lower())
            elif name in ("allow", "disallow") and agents:
                if value:
                    rules.append(RobotsRule(value, name == "allow"))
            elif name == "sitemap" and value:
                sitemaps.append(value)
        finish_group()
        if not groups:
            raise ValueError("Robots response had no usable User-agent groups.")
        return cls(groups, sitemaps, http_status, content_type, elapsed_ms)

    def can_fetch(self, user_agent: str, url: str) -> bool:
        ua = user_agent.lower()
        matching = [(len(agent), group) for group in self.groups for agent in group.agents
                    if agent != "*" and agent in ua]
        if matching:
            specificity = max(length for length, _ in matching)
            selected = [group for length, group in matching if length == specificity]
        else:
            selected = [group for group in self.groups if "*" in group.agents]
        if not selected:
            return True

        parsed = urlparse(url)
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        matches: list[tuple[int, bool]] = []
        for group in selected:
            for rule in group.rules:
                anchored = rule.path.endswith("$")
                pattern = rule.path[:-1] if anchored else rule.path
                regex = "^" + "".join(".*" if char == "*" else re.escape(char) for char in pattern)
                if anchored:
                    regex += "$"
                if re.search(regex, target):
                    specificity = len(pattern.replace("*", ""))
                    matches.append((specificity, rule.allow))
        if not matches:
            return True
        longest = max(length for length, _ in matches)
        return any(allow for length, allow in matches if length == longest)

    def site_maps(self) -> list[str]:
        return list(self._sitemaps)


_ROBOTS_CACHE: dict[str, tuple[float, RobotsPolicy]] = {}


def fetch_bounded_response(url: str, max_bytes: int, timeout: float | None = None) -> BoundedResponse:
    chunks, size = [], 0
    started = time.perf_counter()
    headers = dict(DEFAULT_REQUEST_HEADERS)
    host = urlparse(url).netloc.lower()
    if "amazon.in" in host:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": "https://www.amazon.in/",
            "Connection": "keep-alive",
        }
    elif "ajio.com" in host:
        headers["Referer"] = "https://www.ajio.com/"
    with httpx.Client(timeout=timeout or settings.request_timeout_seconds, follow_redirects=False,
                      headers=headers) as client:
        with client.stream("GET", url) as response:
            content_type = response.headers.get("content-type")
            if response.is_redirect or not 200 <= response.status_code < 300:
                return BoundedResponse(response.status_code, content_type, b"",
                                       int((time.perf_counter() - started) * 1000))
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise ValueError("Retailer response exceeded configured size limit.")
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("Retailer response exceeded configured size limit.")
                chunks.append(chunk)
    return BoundedResponse(response.status_code, content_type, b"".join(chunks), int((time.perf_counter() - started) * 1000))


def _raise_for_response(url: str, response: BoundedResponse) -> None:
    if response.status_code in (301, 302, 303, 307, 308):
        raise ValueError(f"Retailer returned HTTP {response.status_code}; redirect not followed.")
    if not 200 <= response.status_code < 300:
        request = httpx.Request("GET", url)
        raw = httpx.Response(response.status_code, request=request, headers={"content-type": response.content_type or ""})
        raise httpx.HTTPStatusError(f"Retailer returned HTTP {response.status_code}.", request=request, response=raw)


def fetch_bounded_bytes(url: str, max_bytes: int, timeout: float | None = None) -> bytes:
    response = fetch_bounded_response(url, max_bytes, timeout)
    _raise_for_response(url, response)
    return response.body


def fetch_bounded_text(url: str, max_bytes: int, timeout: float | None = None) -> str:
    return fetch_bounded_bytes(url, max_bytes, timeout).decode("utf-8", errors="replace")


def _robots_for(url: str, deadline: float | None = None) -> RobotsPolicy:
    if deadline is not None and time.monotonic() >= deadline:
        raise AccessCheckError("Overall discovery deadline reached before robots check.", "deadline_exceeded")
    parts = urlparse(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    cached = _ROBOTS_CACHE.get(origin)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    robots_url = urlunparse((parts.scheme, parts.netloc, "/robots.txt", "", "", ""))
    validate_public_product_url(robots_url.replace("/robots.txt", "/"))
    started = time.perf_counter()
    response = None
    try:
        timeout = 5.0 if deadline is None else min(5.0, deadline - time.monotonic())
        if timeout <= 0:
            raise AccessCheckError("Overall discovery deadline reached before robots request.", "deadline_exceeded")
        response = fetch_bounded_response(robots_url, 256_000, timeout=timeout)
        elapsed = int((time.perf_counter() - started) * 1000)
        if response.status_code != 200:
            raise AccessCheckError(f"robots.txt returned HTTP {response.status_code} ({response.content_type or 'unknown content type'}).",
                                   "rules_unavailable", response.status_code, response.content_type, elapsed)
        media_type = (response.content_type or "").split(";", 1)[0].strip().lower()
        if media_type and media_type not in ("text/plain", "text/robots"):
            raise AccessCheckError(f"robots.txt returned non-text content ({media_type}).",
                                   "rules_unavailable", response.status_code, response.content_type, elapsed)
        policy = RobotsPolicy.parse(response.text, response.status_code, response.content_type, elapsed)
        _ROBOTS_CACHE[origin] = (time.monotonic() + ROBOTS_TTL_SECONDS, policy)
        return policy
    except AccessCheckError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        raise AccessCheckError(f"Access rules unavailable after {elapsed} ms: {str(exc)[:160]}",
                               "rules_unavailable", response.status_code if response else None,
                               response.content_type if response else None, elapsed) from exc


def validate_public_product_url(url: str) -> str:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The product URL contains an invalid port.") from exc
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or port not in (None, 443):
        raise ValueError("Only HTTPS product URLs on an enabled retailer domain are accepted.")
    if not adapter_for_url(url):
        raise ValueError("The URL host is not one of the seven configured retailer domains.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Retailer host could not be resolved.") from exc
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if not ip.is_global:
            raise ValueError("Retailer host resolved to a non-public address.")
    return url


def validate_permitted_page(url: str, deadline: float | None = None) -> str:
    if deadline is not None and time.monotonic() >= deadline:
        raise AccessCheckError("Overall discovery deadline reached before page check.", "deadline_exceeded")
    validate_public_product_url(url)
    policy = _robots_for(url, deadline)
    if not policy.can_fetch("PriceTruthAI", url):
        raise AccessCheckError("Retailer robots rules disallow this URL; no request was made.", "disallowed",
                               policy.http_status, policy.content_type, policy.elapsed_ms)
    return url


def permitted_sitemaps(platform_adapter, deadline: float | None = None) -> list[str]:
    homepage = f"https://www.{platform_adapter.platform.domains[0]}/"
    policy = _robots_for(homepage, deadline)
    return [url for url in policy.site_maps()
            if platform_adapter.supports_url(url) and policy.can_fetch("PriceTruthAI", url)]
