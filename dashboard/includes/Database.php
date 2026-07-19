<?php
/**
 * Database.php — Güvenli PDO bağlantı katmanı (Singleton)
 * - Prepared statement zorunlu (SQL injection'a karşı)
 * - Emülasyon kapalı: parametreler MySQL tarafında bağlanır
 * - Kimlik bilgileri koddan değil ortam değişkenlerinden okunur
 */
declare(strict_types=1);

final class Database
{
    private static ?PDO $instance = null;

    // new Database() engellenir; tek giriş noktası getConnection()
    private function __construct() {}
    private function __clone() {}

    public static function getConnection(): PDO
    {
        if (self::$instance === null) {
            // Kimlik bilgileri .env / sunucu ortamından gelir, asla hard-code edilmez
            $dsn = sprintf(
                'mysql:host=%s;dbname=%s;charset=utf8mb4',
                getenv('DB_HOST') ?: '127.0.0.1',
                getenv('DB_NAME') ?: 'market_intel'
            );

            $options = [
                PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION, // Hatalar exception fırlatır
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,       // İlişkisel dizi döner
                PDO::ATTR_EMULATE_PREPARES   => false,                  // Gerçek prepared statement
                PDO::ATTR_PERSISTENT         => false,                  // Bağlantı havuzunu web sunucusuna bırak
            ];

            try {
                self::$instance = new PDO($dsn, getenv('DB_USER'), getenv('DB_PASS'), $options);
            } catch (PDOException $e) {
                // Gerçek hata log'a; kullanıcıya parola/host sızdıran mesaj GÖSTERİLMEZ
                error_log('[DB] Bağlantı hatası: ' . $e->getMessage());
                throw new RuntimeException('Veritabanına şu anda ulaşılamıyor.');
            }
        }
        return self::$instance;
    }
}

/* ---- Kullanım örneği: parametreli, güvenli sorgu ---- */
try {
    $db   = Database::getConnection();
    $stmt = $db->prepare(
        'SELECT price, scraped_at
           FROM price_snapshots
          WHERE product_id = :pid AND scraped_at >= :since
          ORDER BY scraped_at DESC
          LIMIT 100'
    );
    $stmt->execute([':pid' => 42, ':since' => '2026-07-01 00:00:00']);
    $rows = $stmt->fetchAll(); // idx_product_time index'ini kullanır
} catch (RuntimeException $e) {
    http_response_code(503);
    echo $e->getMessage();
}
