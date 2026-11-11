"""Polite HTTP for feeds: an honest User-Agent, robots.txt, timeouts and retries.

Standard library only. Three rules:

- Identify the client. The User-Agent names the project and links to it, so
  a site owner can see who is calling and why.
- Respect robots.txt (RFC 9309). A feed the site disallows is skipped and
  shows up in source health as an error instead of being fetched anyway.
- Retry only what can succeed later: timeouts, connection errors, 429 and
  5xx, with exponential backoff and jitter. A 404 or 403 is final.
"""

from __future__ import annotations

import logging
import random
import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from . import __version__

log = logging.getLogger(__name__)

PROJECT_URL = "https://github.com/guyshalom1/osint-news-monitor"
USER_AGENT = f"osint-news-monitor/{__version__} (+{PROJECT_URL})"
ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5"

TIMEOUT_SECONDS = 20
RETRIES = 3
BACKOFF_SECONDS = 2.0        # 2s, 4s, 8s, each plus up to 1s of jitter
MAX_RETRY_AFTER = 60.0       # never sleep longer than this on a server's request
RETRY_STATUS = {429, 500, 502, 503, 504}

Opener = Callable[..., Any]


class FetchError(RuntimeError):
    """A request that failed for good, after any retries."""


@dataclass(frozen=True)
class Response:
    body: bytes
    content_type: str


def _retry_after(err: urllib.error.HTTPError) -> float | None:
    """Seconds the server asked us to wait, if it said so in plain seconds."""
    value = err.headers.get("Retry-After") if err.headers else None
    try:
        return min(float(value), MAX_RETRY_AFTER) if value else None
    except ValueError:   # an HTTP date instead of seconds: fall back to backoff
        return None


def fetch(url: str, *, timeout: float = TIMEOUT_SECONDS, retries: int = RETRIES,
          backoff: float = BACKOFF_SECONDS, opener: Opener = urllib.request.urlopen,
          sleep: Callable[[float], None] = time.sleep) -> Response:
    """GET a URL. Retries transient failures, raises FetchError on the rest."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": ACCEPT})
    for attempt in range(retries + 1):
        wait: float | None = None
        try:
            with opener(request, timeout=timeout) as reply:
                headers = getattr(reply, "headers", None)
                content_type = headers.get("Content-Type", "") if headers else ""
                return Response(reply.read(), content_type or "")
        except urllib.error.HTTPError as err:
            if err.code not in RETRY_STATUS:
                raise FetchError(f"HTTP {err.code} {err.reason}") from err
            reason, wait = f"HTTP {err.code}", _retry_after(err)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            reason = str(getattr(err, "reason", err)) or type(err).__name__
        if attempt == retries:
            raise FetchError(f"{reason} after {retries + 1} attempts")
        delay = wait if wait is not None else backoff * 2 ** attempt + random.uniform(0, 1)
        log.info("retrying %s in %.1fs (%s)", url, delay, reason)
        sleep(delay)
    raise AssertionError("unreachable")   # the loop always returns or raises


DISALLOW_ALL = "User-agent: *\nDisallow: /"


class Robots:
    """robots.txt answers, fetched once per site per run."""

    def __init__(self, opener: Opener = urllib.request.urlopen) -> None:
        self._opener = opener
        self._rules: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _load(self, site: str) -> urllib.robotparser.RobotFileParser | None:
        """Parsed rules for a site, or None when everything is allowed."""
        request = urllib.request.Request(
            f"{site}/robots.txt", headers={"User-Agent": USER_AGENT})
        parser = urllib.robotparser.RobotFileParser()
        try:
            with self._opener(request, timeout=TIMEOUT_SECONDS) as reply:
                text = reply.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as err:
            if 400 <= err.code < 500:
                return None                 # RFC 9309: no robots.txt, no restrictions
            text = DISALLOW_ALL             # server error: assume disallowed
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            text = DISALLOW_ALL             # unreachable: assume disallowed
        parser.parse(text.splitlines())
        return parser

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        site = f"{parts.scheme}://{parts.netloc}"
        if site not in self._rules:
            self._rules[site] = self._load(site)
        rules = self._rules[site]
        return rules is None or rules.can_fetch(USER_AGENT, url)
