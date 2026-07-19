"""
example_static.py — Statik (JS gerektirmeyen) siteler icin sablon bot.
Gercek bir site eklerken: bu dosyayi kopyala, CSS secicilerini ve
get_target_urls() listesini hedef siteye gore degistir.
"""

from __future__ import annotations

import logging
from typing import Any

from bs4 import BeautifulSoup

from base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class ExampleStaticScraper(BaseScraper):
    """Ornek: sunucu tarafinda render edilen bir katalog sayfasi."""

    # --- Bu blogu gercek siteye gore degistir -----------------------------
    _LISTING_SELECTOR = "div.product-card"       # PLACEHOLDER
    _NAME_SELECTOR = ".product-name"             # PLACEHOLDER
    _PRICE_SELECTOR = ".product-price"           # PLACEHOLDER
    _CODE_ATTR = "data-sku"                      # PLACEHOLDER
    _LINK_SELECTOR = "a.product-link"            # PLACEHOLDER
    _STOCK_SELECTOR = ".stock-badge"             # PLACEHOLDER
    _IMAGE_SELECTOR = "img.product-image"        # PLACEHOLDER
    # -----------------------------------------------------------------------

    @property
    def platform_name(self) -> str:
        return "example_static_site"

    @property
    def render_mode(self) -> str:
        return "static"

    def get_target_urls(self) -> list[str]:
        # PLACEHOLDER: gercek kategori/listeleme URL'leri buraya
        return ["https://example.com/catalog?page=1"]

    def parse(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[dict[str, Any]] = []

        for card in soup.select(self._LISTING_SELECTOR):
            try:
                name_el = card.select_one(self._NAME_SELECTOR)
                price_el = card.select_one(self._PRICE_SELECTOR)
                link_el = card.select_one(self._LINK_SELECTOR)
                image_el = card.select_one(self._IMAGE_SELECTOR)
                stock_el = card.select_one(self._STOCK_SELECTOR)

                if name_el is None or price_el is None or link_el is None:
                    # Karttaki zorunlu alanlardan biri yoksa bu karti atla
                    raise ValueError("zorunlu HTML elemani bulunamadi")

                # "1.299,90 TL" gibi metinden sadece rakamlari cikar
                price_text = price_el.get_text(strip=True)
                price_clean = (
                    price_text.replace("TL", "").replace(".", "").replace(",", ".").strip()
                )

                items.append({
                    "name": name_el.get_text(strip=True),
                    "price": price_clean,
                    "external_code": card.get(self._CODE_ATTR, "").strip(),
                    "product_url": link_el.get("href", "").strip(),
                    "stock_status": "in_stock" if stock_el is None else self._map_stock(stock_el.get_text(strip=True)),
                    "image_url": image_el.get("src") if image_el is not None else None,
                })
            except Exception as exc:  # noqa: BLE001 - tek kart hatasi tum sayfayi durdurmamali
                logger.warning("[%s] urun karti atlandi: %s", self.platform_name, exc)
                continue

        return items

    @staticmethod
    def _map_stock(raw_text: str) -> str:
        """Site metnini schema.sql ENUM degerlerine cevirir."""
        text = raw_text.lower()
        if "tukendi" in text or "stokta yok" in text:
            return "out_of_stock"
        if "sinirli" in text or "son" in text:
            return "limited"
        if "stokta" in text:
            return "in_stock"
        return "unknown"
