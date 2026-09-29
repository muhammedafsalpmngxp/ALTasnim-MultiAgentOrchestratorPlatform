"""Fetch pages with httpx and extract the main content with Trafilatura.

Tiers per URL:
  1. httpx GET -> Trafilatura            (fast path, static pages)
  2. Playwright render -> Trafilatura    (optional, JS-heavy pages)
  3. caller falls back to the search snippet
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura
from cachetools import TTLCache

from web_search_agent.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedPage:
    url: str
    text: str
    title: str | None = None
    author: str | None = None
    published_date: str | None = None
    method: Literal["trafilatura", "playwright+trafilatura"] = "trafilatura"


def _trafilatura_json(html: str, url: str, favor_precision: bool) -> dict | None:
    raw = trafilatura.extract(
        html,
        url=url,
        output_format="json",
        with_metadata=True,
        include_comments=False,
        include_tables=True,
        include_images=False,
        favor_precision=favor_precision,
        favor_recall=not favor_precision,
        # deduplicate stays off: its cache is process-global and would blank pages fetched again later.
    )
    return json.loads(raw) if raw else None


def extract_with_trafilatura(html: str, url: str, min_chars: int = 200) -> ExtractedPage | None:
    """Return main text + metadata, or None if nothing useful was found. CPU bound - call in a thread.

    Precision mode first (cleanest text for the LLM); recall mode if that strips the page too far.
    """
    data = _trafilatura_json(html, url, favor_precision=True)
    if not data or len(data.get("text") or "") < min_chars:
        data = _trafilatura_json(html, url, favor_precision=False) or data
    if not data:
        return None
    text = (data.get("text") or data.get("raw_text") or "").strip()
    if not text:
        return None
    return ExtractedPage(
        url=url,
        text=text,
        title=data.get("title"),
        author=data.get("author"),
        published_date=data.get("date"),
    )


class Scraper:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self._client = client
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_fetches)
        self._robots: TTLCache[str, RobotFileParser | None] = TTLCache(maxsize=2000, ttl=3600)
        self._playwright_missing_logged = False

    async def extract_many(self, urls: list[str]) -> dict[str, ExtractedPage | None]:
        pages = await asyncio.gather(*(self.extract(url) for url in urls))
        return dict(zip(urls, pages, strict=True))

    async def extract(self, url: str) -> ExtractedPage | None:
        # httpx timeouts apply per phase (connect/read/...), so a slow-dripping site could take much
        # longer; this caps the whole page (robots.txt + download + extraction). Late pages use the snippet.
        deadline = self._settings.page_deadline_seconds * (2 if self._settings.use_playwright_fallback else 1)
        try:
            return await asyncio.wait_for(self._extract_one(url), timeout=deadline)
        except TimeoutError:
            logger.info("Gave up on %s after %.0f s", url, deadline)
            return None

    async def _extract_one(self, url: str) -> ExtractedPage | None:
        async with self._semaphore:
            try:
                if not await self._allowed_by_robots(url):
                    logger.info("Skipping %s (disallowed by robots.txt)", url)
                    return None

                min_chars = self._settings.min_extracted_chars
                page = None
                html = await self._fetch(url)
                if html:
                    page = await asyncio.to_thread(extract_with_trafilatura, html, url, min_chars)

                if self._too_short(page) and self._settings.use_playwright_fallback:
                    rendered = await self._render(url)
                    if rendered:
                        rendered_page = await asyncio.to_thread(extract_with_trafilatura, rendered, url, min_chars)
                        if rendered_page and not self._too_short(rendered_page):
                            rendered_page.method = "playwright+trafilatura"
                            page = rendered_page

                return None if self._too_short(page) else page
            except Exception as exc:  # noqa: BLE001 - one bad page must not fail the whole request
                logger.warning("Extraction failed for %s: %s", url, exc)
                return None

    def _too_short(self, page: ExtractedPage | None) -> bool:
        return page is None or len(page.text) < self._settings.min_extracted_chars

    async def _fetch(self, url: str) -> str | None:
        try:
            response = await self._client.get(
                url, timeout=self._settings.fetch_timeout_seconds, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            logger.debug("Fetch failed for %s: %s", url, exc)
            return None
        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400 or ("html" not in content_type and "xml" not in content_type):
            return None
        return response.text

    async def _allowed_by_robots(self, url: str) -> bool:
        if not self._settings.respect_robots_txt:
            return True
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = None
            try:
                response = await self._client.get(f"{origin}/robots.txt", timeout=3.0, follow_redirects=True)
                if response.status_code == 200:
                    parser = RobotFileParser()
                    parser.parse(response.text.splitlines())
            except httpx.HTTPError:
                pass  # unreachable robots.txt = no restrictions
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser is None or parser.can_fetch(self._settings.user_agent, url)

    async def _render(self, url: str) -> str | None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            if not self._playwright_missing_logged:
                logger.warning("USE_PLAYWRIGHT_FALLBACK is on but playwright is not installed")
                self._playwright_missing_logged = True
            return None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(user_agent=self._settings.user_agent)
                    await page.goto(
                        url, timeout=self._settings.fetch_timeout_seconds * 2000, wait_until="networkidle"
                    )
                    return await page.content()
                finally:
                    await browser.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Playwright render failed for %s: %s", url, exc)
            return None
