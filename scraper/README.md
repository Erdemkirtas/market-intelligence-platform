# scraper/ — Kurulum ve Calistirma

## 1. Sanal ortam ve bagimliliklar

```bash
cd market-intel/scraper
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
playwright install chromium
```

## 2. Ortam degiskenleri

Proje kokunde (`market-intel/.env.example`) ornek dosyayi kopyala:

```bash
copy ..\.env.example ..\.env
```

`.env` icindeki `DB_USER`, `DB_PASSWORD`, `DB_NAME` degerlerini gercek
MySQL kimlik bilgilerinle doldur. `database/schema.sql`'i MySQL'e
uygulamadan botlar veri yazamaz.

## 3. Calistirma

```bash
python runner.py
```

Loglar hem konsola hem `scraper/logs/run_<tarih_saat>.log` dosyasina yazilir.

## 4. Yeni bir site botu ekleme

1. `site_scrapers/example_static.py` (veya `example_dynamic.py`, JS-render
   gerektiriyorsa) dosyasini kopyala.
2. CSS secicilerini ve `get_target_urls()` listesini hedef siteye gore
   degistir.
3. Yeni sinifi `runner.py` icindeki `BOT_CLASSES` listesine ekle.
