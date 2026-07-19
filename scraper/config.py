"""
config.py — Scraper agi icin merkezi ayar modulu.
Tum ayarlar .env dosyasindan okunur; kod icine hic bir kimlik bilgisi gomulmez.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# .env dosyasi proje kokunde (market-intel/.env) aranir, scraper/ altinda degil
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

try:
    # override=False: sistem ortam degiskenleri varsa onlar .env'den once gelir
    load_dotenv(dotenv_path=_ENV_PATH, override=False)
except OSError as exc:
    # .env okunamazsa bot tamamen durmamali; sistem env degiskenleriyle devam edilir
    print(f"[config] Uyari: .env okunamadi ({exc}), sistem ortam degiskenleri kullanilacak.")


def _get_int(name: str, default: int) -> int:
    """Ortam degiskenini int'e cevirir; hatali/eksik deger varsayilana duser."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[config] Uyari: {name}='{raw}' int'e cevrilemedi, varsayilan={default} kullaniliyor.")
        return default


def _get_float(name: str, default: float) -> float:
    """Ortam degiskenini float'a cevirir; hatali/eksik deger varsayilana duser."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[config] Uyari: {name}='{raw}' float'a cevrilemedi, varsayilan={default} kullaniliyor.")
        return default


@dataclass(frozen=True)
class DBConfig:
    host: str
    port: int
    name: str
    user: str
    password: str


@dataclass(frozen=True)
class ScraperSettings:
    batch_size: int
    request_timeout: int
    max_retries: int
    rate_limit_delay: float
    max_workers: int
    images_dir: Path


def load_db_config() -> DBConfig:
    """DB baglanti bilgilerini .env'den okur. Zorunlu alan eksikse acikca patlar."""
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    name = os.getenv("DB_NAME")

    # Kimlik bilgisi eksikse sessizce bos string ile devam etmek yerine
    # erken ve anlasilir bir hata vermek, ileride garip DB hatalarini onler
    if not user or not password or not name:
        raise RuntimeError(
            "DB_USER, DB_PASSWORD ve DB_NAME .env icinde tanimli olmali. "
            ".env.example dosyasina bakip .env olusturdugundan emin ol."
        )

    return DBConfig(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=_get_int("DB_PORT", 3306),
        name=name,
        user=user,
        password=password,
    )


def load_scraper_settings() -> ScraperSettings:
    """Scraper davranis ayarlarini (rate limit, retry, batch size vb.) okur."""
    return ScraperSettings(
        batch_size=_get_int("BATCH_SIZE", 500),
        request_timeout=_get_int("REQUEST_TIMEOUT", 15),
        max_retries=_get_int("MAX_RETRIES", 3),
        rate_limit_delay=_get_float("RATE_LIMIT_DELAY", 1.5),
        max_workers=_get_int("MAX_WORKERS", 8),
        images_dir=_PROJECT_ROOT / os.getenv("IMAGES_DIR", "images"),
    )


# Modul yuklenirken bir kez okunur, botlar arasinda paylasilir
DB_CONFIG = load_db_config()
SETTINGS = load_scraper_settings()
