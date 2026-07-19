"""
db_writer.py — MySQL yazma katmani. Sadece database/schema.sql'deki
sutunlarla calisir (AGENTS.md kurali: sema tek dogru kaynak).

Kurallar:
- Fiyatlar Decimal olarak baglanir, asla float'a cevrilmez.
- price_snapshots'a tek tek INSERT YASAK; BATCH_SIZE'lik executemany kullanilir.
- Gorseller diske kaydedilir, DB'ye sadece dosya yolu (image_path) yazilir.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import mysql.connector
import requests
from mysql.connector import Error as MySQLError
from mysql.connector.abstracts import MySQLConnectionAbstract

from base_scraper import ScrapedProduct
from config import DB_CONFIG, SETTINGS

logger = logging.getLogger(__name__)

# Dosya sistemine yazarken bozuk karakterlerden kacinmak icin
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


@contextmanager
def get_connection():
    """Tek bir MySQL baglantisi acar, blok sonunda kapatir. Hata durumunda rollback yapar."""
    conn: MySQLConnectionAbstract | None = None
    try:
        conn = mysql.connector.connect(
            host=DB_CONFIG.host,
            port=DB_CONFIG.port,
            database=DB_CONFIG.name,
            user=DB_CONFIG.user,
            password=DB_CONFIG.password,
        )
        yield conn
        conn.commit()
    except MySQLError:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()


def get_or_create_platform_id(conn: MySQLConnectionAbstract, platform_name: str, base_url: str) -> int:
    """platforms tablosunda platform_name'i arar, yoksa olusturur. platform_id doner."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT platform_id FROM platforms WHERE platform_name = %s",
            (platform_name,),
        )
        row = cursor.fetchone()
        if row is not None:
            cursor.close()
            return row[0]

        cursor.execute(
            "INSERT INTO platforms (platform_name, base_url) VALUES (%s, %s)",
            (platform_name, base_url),
        )
        platform_id = cursor.lastrowid
        cursor.close()
        return platform_id
    except MySQLError as exc:
        logger.error("get_or_create_platform_id basarisiz (%s): %s", platform_name, exc)
        raise


def upsert_products(
    conn: MySQLConnectionAbstract,
    platform_id: int,
    products: list[ScrapedProduct],
) -> dict[str, int]:
    """
    products tablosuna INSERT ... ON DUPLICATE KEY UPDATE ile yazar.
    uq_platform_product(platform_id, external_code) sayesinde mukerrer olusmaz.
    Doner: {external_code: product_id} eslemesi.
    """
    if not products:
        return {}

    upsert_sql = """
        INSERT INTO products (platform_id, external_code, product_name, product_url)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            product_name = VALUES(product_name),
            product_url = VALUES(product_url),
            last_seen_at = CURRENT_TIMESTAMP
    """
    rows = [
        (platform_id, product.external_code, product.name, product.product_url)
        for product in products
    ]

    try:
        cursor = conn.cursor()
        cursor.executemany(upsert_sql, rows)
        cursor.close()
    except MySQLError as exc:
        logger.error("upsert_products basarisiz: %s", exc)
        raise

    # executemany + ON DUPLICATE KEY UPDATE tek tek lastrowid dondurmez;
    # yazilan external_code'lari tek SELECT ile geri okuyup id eslemesi cikariyoruz
    external_codes = [product.external_code for product in products]
    placeholders = ", ".join(["%s"] * len(external_codes))
    select_sql = f"""
        SELECT product_id, external_code
        FROM products
        WHERE platform_id = %s AND external_code IN ({placeholders})
    """

    try:
        cursor = conn.cursor()
        cursor.execute(select_sql, (platform_id, *external_codes))
        mapping = {external_code: product_id for product_id, external_code in cursor.fetchall()}
        cursor.close()
        return mapping
    except MySQLError as exc:
        logger.error("upsert_products id eslemesi okunamadi: %s", exc)
        raise


def insert_snapshots(
    conn: MySQLConnectionAbstract,
    snapshot_rows: list[tuple[int, Decimal, str, str, str | None, datetime]],
) -> int:
    """
    price_snapshots'a (product_id, price, currency, stock_status, image_path, scraped_at)
    satirlarini BATCH_SIZE'lik gruplar halinde executemany ile yazar.
    Doner: basariyla yazilan toplam satir sayisi.
    """
    if not snapshot_rows:
        return 0

    insert_sql = """
        INSERT INTO price_snapshots
            (product_id, price, currency, stock_status, image_path, scraped_at)
        VALUES (%s, %s, %s, %s, %s, %s)
    """

    written = 0
    batch_size = SETTINGS.batch_size

    try:
        cursor = conn.cursor()
        for start in range(0, len(snapshot_rows), batch_size):
            batch = snapshot_rows[start:start + batch_size]
            cursor.executemany(insert_sql, batch)
            written += cursor.rowcount
        cursor.close()
    except MySQLError as exc:
        logger.error("insert_snapshots basarisiz (yazilan=%s): %s", written, exc)
        raise

    return written


def download_image(image_url: str | None, platform_name: str, scraped_on: date) -> str | None:
    """
    Gorseli images/{platform}/{YYYY-MM-DD}/ altina indirir.
    Basarisiz olursa None doner (tarama bu yuzden durmaz, image_path NULL kalir).
    """
    if not image_url:
        return None

    target_dir = SETTINGS.images_dir / platform_name / scraped_on.isoformat()

    try:
        target_dir.mkdir(parents=True, exist_ok=True)

        response = requests.get(image_url, timeout=SETTINGS.request_timeout)
        response.raise_for_status()

        original_name = image_url.rsplit("/", 1)[-1] or "image"
        safe_name = _UNSAFE_FILENAME_CHARS.sub("_", original_name)[:150]
        file_path = target_dir / safe_name

        file_path.write_bytes(response.content)
        return str(file_path)
    except (requests.RequestException, OSError) as exc:
        logger.warning("Gorsel indirilemedi url=%s hata=%s", image_url, exc)
        return None


def build_snapshot_rows(
    products: Iterable[ScrapedProduct],
    product_id_by_code: dict[str, int],
    platform_name: str,
    currency: str = "TRY",
) -> list[tuple[int, Decimal, str, str, str | None, datetime]]:
    """ScrapedProduct listesini insert_snapshots()'in bekledigi tuple formatina cevirir."""
    now = datetime.now()
    today = now.date()
    rows: list[tuple[int, Decimal, str, str, str | None, datetime]] = []

    for product in products:
        product_id = product_id_by_code.get(product.external_code)
        if product_id is None:
            # upsert_products bu urunu dondurmediyse (beklenmedik durum) atla, taramayi durdurma
            logger.warning("product_id bulunamadi, snapshot atlandi: %s", product.external_code)
            continue

        image_path = download_image(product.image_url, platform_name, today)

        rows.append((
            product_id,
            product.price,
            currency,
            product.stock_status,
            image_path,
            now,
        ))

    return rows
