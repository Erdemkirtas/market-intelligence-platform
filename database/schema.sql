-- =====================================================================
-- OTONOM PAZAR İSTİHBARATI PLATFORMU - MySQL 8.x ŞEMASI
-- Motor: InnoDB (FK desteği + satır bazlı kilitleme)
-- Karakter seti: utf8mb4 (Türkçe + emoji içeren ürün adları için)
-- =====================================================================

CREATE DATABASE IF NOT EXISTS market_intel
  CHARACTER SET utf8mb4 COLLATE utf8mb4_turkish_ci;
USE market_intel;

-- ---------------------------------------------------------------------
-- 1) PLATFORMS: Taranan kaynak siteler (küçük, statik "lookup" tablosu)
-- ---------------------------------------------------------------------
CREATE TABLE platforms (
    platform_id   SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    platform_name VARCHAR(100) NOT NULL,
    base_url      VARCHAR(255) NOT NULL,
    is_active     TINYINT(1) NOT NULL DEFAULT 1,   -- Bot bu kaynağı taramalı mı?
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (platform_id),
    UNIQUE KEY uq_platform_name (platform_name)     -- Aynı platform iki kez eklenemez
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 2) PRODUCTS: Platform bazlı ürün kimliği (master tablo)
--    NOT: Fiyat burada TUTULMAZ; fiyat zaman serisidir -> price_snapshots
-- ---------------------------------------------------------------------
CREATE TABLE products (
    product_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    platform_id   SMALLINT UNSIGNED NOT NULL,
    external_code VARCHAR(120) NOT NULL,            -- Sitedeki ürün SKU/slug'ı
    product_name  VARCHAR(500) NOT NULL,
    product_url   VARCHAR(1000) NOT NULL,
    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (product_id),
    -- INDEX: Aynı ürünün mükerrer kaydını engeller + bot "ürün var mı?"
    -- sorgusunu (platform+kod) O(log n) yapar. Milyon satırda kritik.
    UNIQUE KEY uq_platform_product (platform_id, external_code),
    -- INDEX: Panelde isimle arama için prefix index (tam sütun index'i
    -- 500 karakterde şişer; ilk 100 karakter yeterli seçicilik sağlar)
    KEY idx_product_name (product_name(100)),
    CONSTRAINT fk_products_platform
        FOREIGN KEY (platform_id) REFERENCES platforms(platform_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 3) PRICE_SNAPSHOTS: Botların her taramada yazdığı ham veri.
--    EN HIZLI BÜYÜYEN TABLO (milyonlarca satır) -> index disiplini şart.
-- ---------------------------------------------------------------------
CREATE TABLE price_snapshots (
    snapshot_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    product_id   BIGINT UNSIGNED NOT NULL,
    price        DECIMAL(12,2) NOT NULL,            -- FLOAT ASLA: kuruş hatası birikir
    currency     CHAR(3) NOT NULL DEFAULT 'TRY',
    stock_status ENUM('in_stock','out_of_stock','limited','unknown')
                 NOT NULL DEFAULT 'unknown',
    image_path   VARCHAR(500) NULL,                 -- Diskteki görsel yolu (BLOB değil!)
    scraped_at   DATETIME NOT NULL,                 -- Botun veri çektiği an
    PRIMARY KEY (snapshot_id),
    -- INDEX (KRİTİK): "X ürününün fiyat geçmişi" panelin ana sorgusudur.
    -- Kompozit (product_id, scraped_at) sayesinde tarih aralığı taraması
    -- tablo taraması yapmadan doğrudan index üzerinden okunur.
    KEY idx_product_time (product_id, scraped_at),
    -- INDEX: Pandas'ın günlük toplu çekişi ("dünden beri gelen her şey")
    -- ve eski veri temizliği (purge) için tek başına tarih index'i.
    KEY idx_scraped_at (scraped_at),
    CONSTRAINT fk_snapshots_product
        FOREIGN KEY (product_id) REFERENCES products(product_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 4) ANALYSIS_RESULTS: Pandas/NumPy çıktıları (temizlenmiş + özetlenmiş)
--    Ham tabloya dokunmadan panelin okuduğu "ön-hesaplanmış" katman.
-- ---------------------------------------------------------------------
CREATE TABLE analysis_results (
    analysis_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    product_id     BIGINT UNSIGNED NOT NULL,
    analysis_date  DATE NOT NULL,                   -- Analizin kapsadığı gün
    avg_price      DECIMAL(12,2) NOT NULL,
    min_price      DECIMAL(12,2) NOT NULL,
    max_price      DECIMAL(12,2) NOT NULL,
    price_change_pct DECIMAL(6,2) NULL,             -- Önceki güne göre % değişim
    is_outlier     TINYINT(1) NOT NULL DEFAULT 0,   -- Aykırı değer bayrağı (z-score/IQR)
    trend          ENUM('rising','falling','stable') NULL,
    sample_count   INT UNSIGNED NOT NULL DEFAULT 0, -- Kaç snapshot'tan hesaplandı
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (analysis_id),
    -- INDEX: Aynı ürün+gün için tek analiz satırı; Pandas job'ı tekrar
    -- çalışırsa INSERT ... ON DUPLICATE KEY UPDATE ile idempotent olur.
    UNIQUE KEY uq_product_day (product_id, analysis_date),
    -- INDEX: "Bugünün aykırı değerleri" panel sorgusu için
    KEY idx_date_outlier (analysis_date, is_outlier),
    CONSTRAINT fk_analysis_product
        FOREIGN KEY (product_id) REFERENCES products(product_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 5) IMAGE_DETECTIONS: YOLO çıktıları. Bir görselde N nesne olabilir
--    -> snapshot ile 1:N ilişki, her tespit ayrı satır.
-- ---------------------------------------------------------------------
CREATE TABLE image_detections (
    detection_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    snapshot_id   BIGINT UNSIGNED NOT NULL,         -- Hangi taramanın görseli
    label         VARCHAR(100) NOT NULL,            -- YOLO sınıf adı (örn. 'bottle')
    confidence    DECIMAL(5,4) NOT NULL,            -- 0.0000 - 1.0000
    bbox_x        SMALLINT UNSIGNED NOT NULL,       -- Sınırlayıcı kutu (piksel)
    bbox_y        SMALLINT UNSIGNED NOT NULL,
    bbox_w        SMALLINT UNSIGNED NOT NULL,
    bbox_h        SMALLINT UNSIGNED NOT NULL,
    model_version VARCHAR(50) NOT NULL,             -- 'yolov8n-v1.2' -> tekrarlanabilirlik
    detected_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (detection_id),
    -- INDEX: "Bu görselde ne tespit edildi?" (snapshot detay ekranı)
    KEY idx_snapshot (snapshot_id),
    -- INDEX: "Etiketi 'X' olan tüm ürünler" tarzı filtreleme + doğrulama
    -- raporları. confidence eklenmesi eşik filtresini (>= 0.80) hızlandırır.
    KEY idx_label_conf (label, confidence),
    CONSTRAINT fk_detection_snapshot
        FOREIGN KEY (snapshot_id) REFERENCES price_snapshots(snapshot_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;
