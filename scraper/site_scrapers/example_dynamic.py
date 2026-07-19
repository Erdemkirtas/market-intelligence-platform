"""
example_dynamic.py — JavaScript ile render edilen (SPA tarzi) siteler icin
sablon bot. fetch() otomatik olarak Playwright'i kullanir (render_mode="dynamic").
Gercek bir site eklerken: bu dosyayi kopyala, CSS secicilerini degistir.
"""

from __future__ import annotations

import logging
from typing import Any

from bs4 import BeautifulSoup

from base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class ExampleDynamicScraper(BaseScraper):
    """Ornek: urun listesini JS ile sonradan dolduran bir SPA sayfasi."""

    # --- Bu blogu gercek siteye gore degistir -----------------------------
    _LISTING_SELECTOR = "li.product-tile"          # PLACEHOLDER
    _NAME_SELECTOR = ".tile-title"                 # PLACEHOLDER
    _PRICE_SELECTOR = ".tile-price"                # PLACEHOLDER
    _CODE_ATTR = "data-product-id"                 # PLACEHOLDER
    _LINK_SELECTOR = "a.tile-link"                 # PLACEHOLDER
    _STOCK_SELECTOR = ".tile-availability"         # PLACEHOLDER
    _IMAGE_SELECTOR = "img.tile-image"             # PLACEHOLDER
    # -----------------------------------------------------------------------

    @property
    def platform_name(self) -> str:
        return "example_dynamic_site"

    @property
    def render_mode(self) -> str:
        return "dynamic"

    def get_target_urls(self) -> list[str]:
        # PLACEHOLDER: gercek kategori/listeleme URL'leri buraya
        return ["https://example-spa.com/products"]

    def parse(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[dict[str, Any]] = []

        for tile in soup.select(self._LISTING_SELECTOR):
            try:
                name_el = tile.select_one(self._NAME_SELECTOR)
                price_el = tile.select_one(self._PRICE_SELECTOR)
                link_el = tile.select_one(self._LINK_SELECTOR)
                image_el = tile.select_one(self._IMAGE_SELECTOR)
                stock_el = tile.select_one(self._STOCK_SELECTOR)

                if name_el is None or price_el is None or link_el is None:
                    raise ValueError("zorunlu HTML elemani bulunamadi")

                price_text = price_el.get_text(strip=True)
                price_clean = (
                    price_text.replace("TL", "").replace(".", "").replace(",", ".").strip()
                )

                items.append({
                    "name": name_el.get_text(strip=True),
                    "price": price_clean,
                    "external_code": tile.get(self._CODE_ATTR, "").strip(),
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
