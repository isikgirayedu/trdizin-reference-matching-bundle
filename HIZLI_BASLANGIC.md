# 🎯 Hızlı Başlangıç Rehberi

## Entegrasyon Adımlarının Özeti

Sizin rehberinizi projeye entegre etmek için hazırlanan 3 ana belge:

### 📖 1. ENTEGRASYON_REHBERI.md
**İçerik**: Stratejik yol haritası ve genel bakış
- Mevcut uygulamalar ✅
- Eksik bileşenler ❌  
- 4 faz detaylı planı
- Başarı metrikleri

**Kullanım**: İşe başlamadan önce proje bütünü hakkında bil almak için oku.

---

### 📋 2. AKSIYON_PLANI.md
**İçerik**: Günlük görevler ve implementasyon detayları
- Hafta-hafta zamanlama
- Her görev için Python kod şablonları
- Test kontrol listeleri
- Quick start komutları

**Kullanım**: Geliştirme sırasında rehber olarak kullan.

---

### 📦 3. REQUIREMENTS_UPDATE.md
**İçerik**: Gerekli kütüphaneler ve kurulum
- Yeni paket listesi
- Kurulum komutları
- Uyumluluk tablosu
- Sorun giderme

**Kullanım**: İlk kurulumda ve paket güncellemelerinde başvur.

---

## 🚀 İLK HAFTA İçİN - HEMEN BAŞLAYACAKSAN

### Adım 1: Ortam Kurulumu (30 dakika)

```bash
# 1. Projeye git
cd c:\Users\Şükran\trdizin-reference-matching-bundle

# 2. Paketleri kur
pip install fuzzywuzzy python-Levenshtein diskcache plotly

# 3. Test et
python3 -c "import requests, fuzzywuzzy, diskcache; print('✅ Hazır')"
```

### Adım 2: Semantic Scholar Modülü Oluştur (4 saatlik iş)

Dosya: `root_scripts/trdizin_semanticscholar_fallback.py`

AKSIYON_PLANI.md'de bulunan kodu kopyala ve:

```bash
# Küçük test (100 referans)
python3 root_scripts/trdizin_semanticscholar_fallback.py \
  trdizin_crossref_doi_stats_10k/sample_100.jsonl \
  trdizin_crossref_doi_stats_10k/semanticscholar_test.jsonl

# Başarı oranını kontrol et
cat trdizin_crossref_doi_stats_10k/semanticscholar_test.jsonl | grep -c '"found": true'
```

### Adım 3: Eşleşmeyen Referansları Analiz Et (2 saatlik iş)

Dosya: `root_scripts/unmatched_reference_analysis.py`

```bash
# Mevcut unmatched referansları kategorize et
python3 root_scripts/unmatched_reference_analysis.py \
  trdizin_crossref_doi_stats_10k/combined_results.jsonl \
  trdizin_crossref_doi_stats_10k/unmatched_analysis/

# Raporları aç
open trdizin_crossref_doi_stats_10k/unmatched_analysis/unmatched_analysis.md
```

---

## 📊 BEKLENEN SONUÇLAR (İlk Hafta)

✅ **Semantic Scholar entegre**: +2-3% başarı  
✅ **Eşleşmeyen kategorize**: Görünürlük sağlansa  
✅ **Yeni yapı**: root_scripts/* güncellenmiş  

**Başarı Oranı**: 64% → ~67% 📈

---

## 🔄 İLKİ 4 Haftalık Yol Haritası

```
HAFTA 1
└─ Semantic Scholar + Europe PMC
   ├─ Entegrasyon: 3 gün
   └─ Test & Cache: 2 gün
   
HAFTA 2
└─ Eşleşmeyen Analiz + Dashboard
   ├─ Kategorize: 2 gün
   ├─ Raporlama: 1 gün
   └─ Grafik UI: 2 gün
   
HAFTA 3
└─ Performans Optimizasyonu
   ├─ Paralel işlem: 2 gün
   ├─ Caching: 1 gün
   └─ Monitoring: 2 gün
   
HAFTA 4
└─ Doğrulama & Finalizasyon
   ├─ Benchmark: 2 gün
   ├─ Validation: 1 gün
   └─ Dokümantasyon: 2 gün

HEDEF: 75%+ başarı oranı ✨
```

---

## 📂 Dosya Yapısı (Sonra)

```
root_scripts/
├── [MEVCUT]
├── trdizin_crossref_doi_stats.py
├── trdizin_crossref_bibliographic_fallback.py
├── trdizin_openalex_fallback.py
├── trdizin_dergipark_oai_fallback.py
├── trdizin_experiment*.py
│
├── [YENİ - FAZ 1]
├── trdizin_semanticscholar_fallback.py ⭐
├── trdizin_europepmc_fallback.py
│
├── [YENİ - FAZ 2]
├── unmatched_reference_analysis.py ⭐
├── pipeline_statistics_reporter.py
│
├── [YENİ - FAZ 3]
├── parallel_reference_matcher.py
├── rate_limiter_cache.py
├── pipeline_monitor.py
│
├── [YENİ - FAZ 4]
├── benchmark_suite.py
├── validation_checklist.txt
│
└── [REHBER DOSYALARI - KÖKÜ]
    ├── ENTEGRASYON_REHBERI.md 📖
    ├── AKSIYON_PLANI.md 📋
    ├── REQUIREMENTS_UPDATE.md 📦
    └── HIZLI_BASLANGIC.md (bu dosya)
```

---

## 🎯 Başarı Kontrol Listeleri

### Hafta 1 Sonu (Semantic Scholar)
- [ ] `trdizin_semanticscholar_fallback.py` yazıldı
- [ ] 100 referansla test geçti
- [ ] Cache mekanizması çalışıyor
- [ ] Sonuçlar JSON'da kaydedildi
- [ ] Beklenen: +2-3% başarı

### Hafta 2 Sonu (Analiz)
- [ ] Eşleşmeyen referanslar kategorize edildi
- [ ] 8 kategori tanımlanmış
- [ ] JSON, MD, CSV raporları oluşturuldu
- [ ] Dashboard grafikler hazır
- [ ] Beklenen: Görünürlük 100%

### Hafta 3 Sonu (Performans)
- [ ] Paralel işlem 4x+ hızlı
- [ ] Cache hit rate %80+
- [ ] Monitoring aktif
- [ ] Rate limiting çalışıyor
- [ ] Beklenen: İşlem süresinde %75 indirim

### Hafta 4 Sonu (Doğrulama)
- [ ] Benchmark suite tamamlandı
- [ ] Precision %90+
- [ ] Recall %70+
- [ ] Tüm metrikler kaydedildi
- [ ] **Beklenen: 75%+ başarı oranı** ✨

---

## 💡 Pro İpuçları

### Cache Yönetimi
```bash
# Cache'i temizle (gerekirse)
rm -rf ~/.diskcache/

# Cache boyutunu kontrol et
du -h ~/.diskcache/
```

### Rate Limiting
```python
# Semantic Scholar rate limit: 100 req/5 min
# = 20 req/min = 1 req/3 saniye
import time
time.sleep(3)  # Her API çağrısı arasında
```

### Paralel İşlem
```python
# En iyi worker sayısı = CPU core sayısı
import os
num_workers = os.cpu_count()  # Genelde 8-16
```

### Debugging
```bash
# JSON'dan belirli satırı çıkart
head -n 1 results.jsonl | python3 -m json.tool

# Hata sayısı
grep '"error"' results.jsonl | wc -l

# Başarı oranı
grep '"found": true' results.jsonl | wc -l
```

---

## 🆘 Sık Sorulan Sorular

**S: Tüm fázları aynı anda çalıştırabilirim mi?**  
C: Hayır, sırayla yapılması önerilir. Faz 2, Faz 1'e bağlı değildir ama Faz 3, sonuçlarına ihtiyaç duyar.

**S: Ne kadar sürede başarı görürüm?**  
C: Semantic Scholar entegrasyonundan sonra 2-3 gün içinde sonuçları görebilirsin.

**S: API rate limit görürsem ne yapayım?**  
C: Cache dosyaları otomatik kaydedilir. Script'i sonra çalıştırınca devam eder.

**S: Mevcut pipeline'ı bozar mı?**  
C: Hayır, yeni dosyalar oluşturuluyor. Mevcut dosyalar dokunulmaz.

**S: Benchmark'i ne sıklıkta çalıştırmalıyım?**  
C: Haftalık veya her büyük değişiklik sonrası.

---

## 📞 Destek Kaynakları

- **ENTEGRASYON_REHBERI.md**: Stratejik sorular  
- **AKSIYON_PLANI.md**: Teknik detaylar ve kod  
- **REQUIREMENTS_UPDATE.md**: Kurulum sorunları  
- **HIZLI_BASLANGIC.md**: Bu dosya (başlangıç rehberi)  

---

## ✨ Proje Özeti

| Öğe | Durum |
|-----|--------|
| **Mevcut API'lar** | 7 ✅ |
| **Eksik API'lar** | 3 (Semantic Scholar, Europe PMC, PubMed) |
| **Başarı Oranı** | 64.10% → 75%+ |
| **Zaman Tahmini** | 3-4 hafta |
| **Başlangıç Zorluğu** | ⭐ Kolay (template'ler hazır) |
| **Beklenen ROI** | Yüksek (+10% başarı) |

---

**Hazırlayan**: GitHub Copilot  
**Tarih**: 2026-08-14  
**Sürüm**: 1.0  

🎉 **Başlamaya hazır mısın?** → AKSIYON_PLANI.md'yi aç ve Hafta 1'i başlat!
