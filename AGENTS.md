# AGENTS.md — Otonom Pazar İstihbaratı ve Raporlama Platformu

Bu dosyadaki kurallar, bu proje kapsamındaki TÜM görevlerde geçerlidir.

## Kod Kalitesi
- Modüler mimari ve fonksiyonel ayrım gözet; her fonksiyon/sınıf tek sorumluluk taşısın.
- Katı hata yönetimi zorunlu: tüm dış kaynak erişimleri (DB, HTTP, dosya, model çıkarımı)
  try-except (Python) / try-catch (PHP) bloklarıyla sarmalanmalı.
- Sadece istenen göreve odaklan; uzun açıklama paragraflarından kaçın.
- Kod içine kısa, açıklayıcı yorum satırları ekle (ne yaptığını değil, neden öyle
  yapıldığını açıkla).

## Performans
- Önerilen her çözümün olası performans darboğazını (index eksikliği, N+1 sorgu,
  gereksiz tam tablo taraması, senkron I/O vb.) uygulamadan önce değerlendir.

## Veritabanı — Tek Doğru Kaynak
- `database/schema.sql` bu projenin TEK doğru şemasıdır. Tüm kod (PHP, Python) bu
  şemadaki tablo/sütun adlarına birebir uygun yazılmalı; şema dışı varsayım yapılmaz.
- Fiyatlar `DECIMAL` tipinde tutulur (FLOAT kullanılmaz — yuvarlama hatası birikir).
- Görseller veritabanına BLOB olarak değil, disk üzerindeki dosya yoluna referansla
  (`image_path` / `file_path` sütunu) kaydedilir.
- `price_snapshots` tablosuna yazımlar tek tek `INSERT` ile değil, 500-1000 satırlık
  batch'ler halinde `executemany` ile yapılır.

## SQL Tasarım
- İlişkisel kurallara uy: her ilişki uygun Foreign Key ile kurulur, normalizasyon
  bozulmaz.
- Milyon satır ölçeğine ulaşacak tablolarda (`price_snapshots`, `image_detections`)
  sorgu kalıbına uygun index'ler zorunludur (özellikle composite index'ler).
