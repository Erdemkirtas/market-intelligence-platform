"""
base_scraper.py — Tum site botlarinin turedigi soyut temel sinif.
Ortak sorumluluklar burada toplanir: HTTP/tarayici fetch, retry, rate limit,
hata izolasyonu. Alt siniflar sadece "bu site HTML'ini nasil parse ederim"
sorusuna odaklanir.
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from config import SETTINGS

logger = logging.getLogger(__name__)

# Bot tespiti riskini azaltmak icin donen User-Agent havuzu
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
]

# products/price_snapshots ile uyumlu stok durumu degerleri (schema.sql ENUM)
_VALID_STOCK_STATUSES = {"in_stock", "out_of_stock", "limited", "unknown"}

# parse()'in her sozlukte dondurmesi zorunlu alanlar
_REQUIRED_FIELDS = {"name", "price", "external_code", "product_url", "stock_status", "image_url"}


@dataclass
class ScrapedProduct:
    """parse() ciktisinin normalize edilmis, tip-guvenli hali."""

    name: str
    price: Decimal
    external_code: str
    product_url: str
    stock_status: str
    image_url: str | None = None


@dataclass
class ScrapeResult:
    """Bir botun tek calismasinin ozeti: basarili urunler + atlanan hatalar."""

    platform_name: str
    products: list[ScrapedProduct] = field(default_factory=list)
    skipped_count: int = 0


class BaseScraper(ABC):
    """Tum site botlari bu sinifi miras alir."""

    def __init__(self) -> None:
        self._last_request_at: float = 0.0

    # ------------------------------------------------------------------
    # Alt siniflarin doldurmasi ZORUNLU olan kisim
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """platforms.platform_name ile birebir eslesmeli."""

    @property
    @abstractmethod
    def render_mode(self) -> str:
        """'static' -> requests yeterli, 'dynamic' -> JS render (Playwright) gerekli."""

    @abstractmethod
    def parse(self, html: str) -> list[dict[str, Any]]:
        """
        Ham HTML'den urun listesi cikarir.
        Her sozluk name, price, external_code, product_url, stock_status,
        image_url anahtarlarini icermeli.
        """

    @abstractmethod
    def get_target_urls(self) -> list[str]:
        """Bu botun tarayacagi listeleme/kategori sayfalarinin URL listesi."""

    # ------------------------------------------------------------------
    # Ortak altyapi: rate limit + retry'li fetch
    # ------------------------------------------------------------------

    def _respect_rate_limit(self) -> None:
        """Ayni bot icin istekler arasinda RATE_LIMIT_DELAY kadar bekler."""
        elapsed = time.monotonic() - self._last_request_at
        remaining = SETTINGS.rate_limit_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def fetch_static(self, url: str) -> str | None:
        """requests ile HTML ceker. Exponential backoff'lu retry icerir."""
        headers = {"User-Agent": random.choice(_USER_AGENTS)}

        for attempt in range(1, SETTINGS.max_retries + 1):
            self._respect_rate_limit()
            try:
                response = requests.get(url, headers=headers, timeout=SETTINGS.request_timeout)
                response.raise_for_status()
                return response.text
            except requests.RequestException as exc:
                logger.warning(
                    "[%s] fetch_static basarisiz (deneme %s/%s) url=%s hata=%s",
                    self.platform_name, attempt, SETTINGS.max_retries, url, exc,
                )
                if attempt < SETTINGS.max_retries:
                    time.sleep(2 ** attempt)  # exponential backoff: 2s, 4s, 8s...

        logger.error("[%s] fetch_static tum denemeler tukendi url=%s", self.platform_name, url)
        return None

    def fetch_dynamic(self, url: str) -> str | None:
        """Playwright (headless chromium) ile JS-render edilmis HTML ceker."""
        for attempt in range(1, SETTINGS.max_retries + 1):
            self._respect_rate_limit()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page(user_agent=random.choice(_USER_AGENTS))
                        page.goto(url, timeout=SETTINGS.request_timeout * 1000, wait_until="networkidle")
                        html = page.content()
                        return html
                    finally:
                        browser.close()
            except PlaywrightError as exc:
                logger.warning(
                    "[%s] fetch_dynamic basarisiz (deneme %s/%s) url=%s hata=%s",
                    self.platform_name, attempt, SETTINGS.max_retries, url, exc,
                )
                if attempt < SETTINGS.max_retries:
                    time.sleep(2 ** attempt)

        logger.error("[%s] fetch_dynamic tum denemeler tukendi url=%s", self.platform_name, url)
        return None

    def fetch(self, url: str) -> str | None:
        """render_mode'a gore dogru fetch stratejisini secer."""
        if self.render_mode == "static":
            return self.fetch_static(url)
        if self.render_mode == "dynamic":
            return self.fetch_dynamic(url)
        raise ValueError(f"Bilinmeyen render_mode: {self.render_mode!r} ('static' veya 'dynamic' olmali)")

    # ------------------------------------------------------------------
    # Normalize: ham parse ciktisini ScrapedProduct'a cevirir
    # ------------------------------------------------------------------

    def _normalize_item(self, raw_item: dict[str, Any]) -> ScrapedProduct | None:
        """Tek bir urun sozlugunu dogrular ve tipe cevirir. Hatali urun None doner."""
        missing = _REQUIRED_FIELDS - raw_item.keys()
        if missing:
            raise ValueError(f"Eksik alan(lar): {missing}")

        try:
            price = Decimal(str(raw_item["price"]))
        except (InvalidOperation, TypeError) as exc:
            raise ValueError(f"Gecersiz fiyat degeri: {raw_item['price']!r}") from exc

        stock_status = raw_item["stock_status"]
        if stock_status not in _VALID_STOCK_STATUSES:
            stock_status = "unknown"

        return ScrapedProduct(
            name=str(raw_item["name"]).strip(),
            price=price,
            external_code=str(raw_item["external_code"]).strip(),
            product_url=str(raw_item["product_url"]).strip(),
            stock_status=stock_status,
            image_url=raw_item.get("image_url") or None,
        )

    # ------------------------------------------------------------------
    # Sablon metot: fetch -> parse -> normalize
    # ------------------------------------------------------------------

    def scrape(self) -> ScrapeResult:
        """
        Botun tam akisini yonetir. Tek bir urundeki parse/normalize hatasi
        tum taramayi durdurmaz; hatali urun loglanip atlanir.
        """
        result = ScrapeResult(platform_name=self.platform_name)

        for url in self.get_target_urls():
            html = self.fetch(url)
            if html is None:
                # Sayfa hic cekilemedi; bu sayfayi atla, digerlerine devam et
                result.skipped_count += 1
                continue

            try:
                raw_items = self.parse(html)
            except Exception as exc:  # noqa: BLE001 - bot cokmemeli, her hatayi yakala
                logger.error("[%s] parse() hata verdi url=%s hata=%s", self.platform_name, url, exc)
                result.skipped_count += 1
                continue

            for raw_item in raw_items:
                try:
                    product = self._normalize_item(raw_item)
                except Exception as exc:  # noqa: BLE001 - tek urun hatasi taramayi durdurmamali
                    logger.warning("[%s] urun atlandi: %s | veri=%s", self.platform_name, exc, raw_item)
                    result.skipped_count += 1
                    continue

                if product is not None:
                    result.products.append(product)

        logger.info(
            "[%s] tarama bitti: %s urun basarili, %s atlandi",
            self.platform_name, len(result.products), result.skipped_count,
        )
        return result
