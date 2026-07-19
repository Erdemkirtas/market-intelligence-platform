"""
runner.py — Kayitli tum botlari ThreadPoolExecutor(MAX_WORKERS) ile
eszamanli calistiran orkestrasyon script'i. Bir botun (scrape veya DB
yazma) hatasi digerlerini etkilemez; sonuclar bot bazinda toplanir.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from base_scraper import BaseScraper
from config import SETTINGS
from db_writer import build_snapshot_rows, get_connection, get_or_create_platform_id, insert_snapshots, upsert_products
from site_scrapers.example_dynamic import ExampleDynamicScraper
from site_scrapers.example_static import ExampleStaticScraper

# Yeni bir site botu eklendikce buraya kaydedilir
BOT_CLASSES: list[type[BaseScraper]] = [
    ExampleStaticScraper,
    ExampleDynamicScraper,
]

_LOG_DIR = Path(__file__).resolve().parent / "logs"
logger = logging.getLogger("runner")


def _configure_logging() -> None:
    """Hem dosyaya hem konsola loglayan handler'lari kurar."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _LOG_DIR / f"run_{time.strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def run_bot(bot_cls: type[BaseScraper]) -> dict[str, Any]:
    """Tek bir botu calistirir: scrape() + DB yazimi. Her adim ayri try-except ile korunur."""
    bot_name = bot_cls.__name__

    try:
        scraper = bot_cls()
        result = scraper.scrape()
    except Exception as exc:  # noqa: BLE001 - bir botun coku digerini durdurmamali
        logger.error("[%s] scrape() beklenmeyen hata: %s", bot_name, exc)
        return {"platform": bot_name, "success": False, "product_count": 0, "error_count": 1}

    if not result.products:
        logger.warning("[%s] yazilacak urun yok (skipped=%s)", result.platform_name, result.skipped_count)
        return {
            "platform": result.platform_name,
            "success": True,
            "product_count": 0,
            "error_count": result.skipped_count,
        }

    try:
        target_urls = scraper.get_target_urls()
        base_url = target_urls[0] if target_urls else ""

        with get_connection() as conn:
            platform_id = get_or_create_platform_id(conn, result.platform_name, base_url)
            product_id_by_code = upsert_products(conn, platform_id, result.products)
            snapshot_rows = build_snapshot_rows(result.products, product_id_by_code, result.platform_name)
            written = insert_snapshots(conn, snapshot_rows)
    except Exception as exc:  # noqa: BLE001 - DB hatasi diger botlarin yazimini engellememeli
        logger.error("[%s] DB yazma hatasi: %s", result.platform_name, exc)
        return {
            "platform": result.platform_name,
            "success": False,
            "product_count": len(result.products),
            "error_count": result.skipped_count + 1,
        }

    return {
        "platform": result.platform_name,
        "success": True,
        "product_count": written,
        "error_count": result.skipped_count,
    }


def main() -> None:
    _configure_logging()
    start_time = time.monotonic()
    logger.info("Tarama basladi: %s bot, MAX_WORKERS=%s", len(BOT_CLASSES), SETTINGS.max_workers)

    summaries: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=SETTINGS.max_workers) as executor:
        future_to_bot: dict[Future, str] = {
            executor.submit(run_bot, bot_cls): bot_cls.__name__ for bot_cls in BOT_CLASSES
        }

        for future in as_completed(future_to_bot):
            bot_name = future_to_bot[future]
            try:
                summaries.append(future.result())
            except Exception as exc:  # noqa: BLE001 - son guvenlik agi, tekil bot hatasi geneli durdurmaz
                logger.error("[%s] beklenmeyen ust seviye hata: %s", bot_name, exc)
                summaries.append({"platform": bot_name, "success": False, "product_count": 0, "error_count": 1})

    duration = time.monotonic() - start_time
    total_products = sum(item["product_count"] for item in summaries)
    total_errors = sum(item["error_count"] for item in summaries)

    logger.info(
        "Tarama bitti: sure=%.1fs, toplam_urun=%s, toplam_hata=%s",
        duration, total_products, total_errors,
    )
    for item in summaries:
        logger.info(
            "  - %s: basarili=%s, urun=%s, hata=%s",
            item["platform"], item["success"], item["product_count"], item["error_count"],
        )


if __name__ == "__main__":
    main()
