# ✅ ENTEGRASYONİZASYON KONTROL LİSTESİ

**Proje**: TR Dizin Referans Eşleştirme Entegrasyonu  
**Başlangıç**: 2026-08-14  
**Hedef Bitiş**: 2026-09-15 (4 hafta)  
**Hedef Başarı**: 75%+ 

---

## 📋 FAZ 1: YENI API ENTEGRASYONLARI (Hafta 1)

### Semantic Scholar Fallback
- [ ] **Görev 1.1**: Script yazma (`trdizin_semanticscholar_fallback.py`)
  - [ ] API sınıfı oluşturma
  - [ ] Title similarity matching (fuzzywuzzy)
  - [ ] Cache mekanizması
  - [ ] Error handling
  - [ ] Main() function

- [ ] **Görev 1.2**: Test (100 referans)
  - [ ] Test seti hazırlama
  - [ ] Script çalıştırma
  - [ ] Output JSON kontrolü
  - [ ] Match accuracy > 80%
  - [ ] Performance: <100ms/ref

- [ ] **Görev 1.3**: Rate limiting
  - [ ] Politeness delay (1 sec) uygulanmış
  - [ ] Cache hits %80+
  - [ ] Timeout handling

- [ ] **Çıktı**: `trdizin_crossref_doi_stats_10k/semanticscholar_fallback/results.jsonl`
  - [ ] Dosya boyutu > 1MB
  - [ ] Satır sayısı = 100 (test) veya 10000 (full)
  - [ ] Beklenen eşleşme: %3-5

### Europe PMC Fallback
- [ ] **Görev 1.4**: Script yazma (`trdizin_europepmc_fallback.py`)
  - [ ] API sınıfı oluşturma
  - [ ] PMID/PMCID çıkarma
  - [ ] DOI extraction
  - [ ] Error handling

- [ ] **Görev 1.5**: Test (50 biyomedikal referans)
  - [ ] Test seti hazırlama
  - [ ] Script çalıştırma
  - [ ] Output JSON kontrolü
  - [ ] Match rate başarısı ölçme

- [ ] **Çıktı**: `trdizin_crossref_doi_stats_10k/europepmc_fallback/results.jsonl`

### Hafta 1 Finalı
- [ ] Semantic Scholar tamamlandı ✅
- [ ] Europe PMC tamamlandı ✅
- [ ] Başarı oranı: 64% → 67% (hedef)
- [ ] Tüm çıktılar kaydedildi

---

## 📊 FAZ 2: ESLESMEYEN ANALIZ & DASHBOARD (Hafta 2)

### Eşleşmeyen Referansları Kategorize
- [ ] **Görev 2.1**: Analyzer sınıfı yazma
  - [ ] 8 kategori tanımlanmış
    - [ ] Gri Edebiyat (Report, Memorandum, vb)
    - [ ] Tezler (Thesis, Dissertation, vb)
    - [ ] Konferans (Conference, Proceedings)
    - [ ] Yasal/Patent (Law, Patent, vb)
    - [ ] Eski Yayınlar (<1985)
    - [ ] Türkçe Kaynaklar
    - [ ] Web Kaynakları
    - [ ] Özel Koleksiyonlar
  - [ ] Keyword matching algoritması
  - [ ] Tarih range checking
  - [ ] Fallback: 'Diğer' kategorisi

- [ ] **Görev 2.2**: Analiz çalıştırma
  - [ ] Input: combined_results.jsonl
  - [ ] Tüm 10000 referans işlenmiş
  - [ ] Kategorize oranı: 100%

- [ ] **Görev 2.3**: Raporlama
  - [ ] JSON çıktı oluşturulmuş
    - [ ] Toplam unmatched
    - [ ] Kategori sayıları
    - [ ] Yüzde dağılımı
    - [ ] Örnek referanslar (10 per category)
  - [ ] Markdown raporu oluşturulmuş
  - [ ] CSV dosyaları (kategori per dosya)

- [ ] **Çıktılar**: `trdizin_crossref_doi_stats_10k/unmatched_analysis/`
  - [ ] `unmatched_analysis.json`
  - [ ] `unmatched_analysis.md`
  - [ ] `unmatched_*.csv` (8 kategori dosyası)

### İstatistik Dashboardi
- [ ] **Görev 2.4**: HTML dashboard oluşturma
  - [ ] Başlık ve header
  - [ ] Genel metrikler
    - [ ] Toplam eşleşen sayısı
    - [ ] Eşleşemeyen sayısı
    - [ ] Başarı yüzdesi
  - [ ] Grafikler
    - [ ] Kaynağa göre bar chart
    - [ ] Kategori dağılımı pie chart
    - [ ] Zaman serisi trend (opsiyonel)

- [ ] **Görev 2.5**: Plotly entegrasyonu
  - [ ] JSON veri kaynağı bağlantısı
  - [ ] Real-time güncelleme
  - [ ] Responsive tasarım

- [ ] **Çıktı**: `github_dashboard/reference_stats.html`
  - [ ] Dosya boyutu > 50KB
  - [ ] Tarayıcıda açılıyor
  - [ ] Grafikler görünüyor

### Hafta 2 Finalı
- [ ] Eşleşmeyen kategorize tamamlandı ✅
- [ ] Raporlar oluşturuldu ✅
- [ ] Dashboard erişilebilir ✅
- [ ] Katmansal görünürlük sağlanmış

---

## ⚡ FAZ 3: PERFORMANS OPTIMIZASYONU (Hafta 3)

### Paralel İşlem
- [ ] **Görev 3.1**: Paralel matcher yazma
  - [ ] ParallelReferenceMatcher sınıfı
  - [ ] Multiprocessing Pool setup
  - [ ] Worker count = CPU cores
  - [ ] Chunk size = 100

- [ ] **Görev 3.2**: Worker function
  - [ ] Tek referans işleme (_match_single_reference)
  - [ ] API çağrıları (crossref, openalex, vb)
  - [ ] Best match seçimi

- [ ] **Görev 3.3**: Output handling
  - [ ] Sonuçları dosyaya yazma (paralel safe)
  - [ ] Progress tracking
  - [ ] Error handling

- [ ] **Görev 3.4**: Performance test
  - [ ] Sequential çalışma: X saniye
  - [ ] Parallel çalışma: X/4 saniye (hedef)
  - [ ] Memory usage monitörleme
  - [ ] CPU utilization %90+

- [ ] **Çıktı**: `root_scripts/parallel_reference_matcher.py`
  - [ ] Script yazılı ve test edilmiş
  - [ ] Performance gain: 4x+ ✓

### Caching & Rate Limiting
- [ ] **Görev 3.5**: Cache sistem kurulumu
  - [ ] diskcache kütüphanesi
  - [ ] Cache directory: `.cache/api_cache`
  - [ ] TTL: 24 saatlik expiry
  - [ ] Max size: 500MB

- [ ] **Görev 3.6**: Rate limiter
  - [ ] API başına rate config
    - [ ] Crossref: 50 req/sec
    - [ ] OpenAlex: 10000 req/hour
    - [ ] Semantic Scholar: 100 req/5 min
    - [ ] Europe PMC: 20 req/sec
  - [ ] Request throttling
  - [ ] Retry logic (exponential backoff)

- [ ] **Görev 3.7**: Testing
  - [ ] Cache hit rate ölçülmüş
  - [ ] Beklenen: %80+
  - [ ] Rate limits hiç exceeded edilmemiş

- [ ] **Çıktı**: `root_scripts/rate_limiter_cache.py`
  - [ ] Script yazılı
  - [ ] Entegre edilmiş

### Monitoring & Logging
- [ ] **Görev 3.8**: Monitoring sistem
  - [ ] PipelineMonitor sınıfı
  - [ ] Metrics tracking
    - [ ] Processed count
    - [ ] Matched count
    - [ ] Error count
    - [ ] API calls per source
  - [ ] Real-time logging

- [ ] **Görev 3.9**: Rapor oluşturma
  - [ ] JSON format çıktı
  - [ ] Execution time
  - [ ] Success rate
  - [ ] API call distribution

- [ ] **Çıktı**: `root_scripts/pipeline_monitor.py`
  - [ ] Script yazılı
  - [ ] Log dosyaları düzenli

### Hafta 3 Finalı
- [ ] Paralel işlem çalışıyor ✅
- [ ] Cache hit rate %80+ ✅
- [ ] Rate limiting aktif ✅
- [ ] Monitoring sistemi aktif ✅
- [ ] Performance: 4x+ hızlı ✅

---

## 🧪 FAZ 4: DOĞRULAMA & FİNAL (Hafta 4)

### Benchmark Suite
- [ ] **Görev 4.1**: Test setleri hazırlama
  - [ ] DOI-rich referanslar (200)
  - [ ] DOI-poor referanslar (300)
  - [ ] Biyomedikal referanslar (200)
  - [ ] Eski yayınlar (100)
  - [ ] Türkçe kaynaklar (200)
  - [ ] **Toplam**: 1000 test referansı

- [ ] **Görev 4.2**: Benchmark metodolojisi
  - [ ] Crossref-only pipeline
  - [ ] Crossref + OpenAlex
  - [ ] Full pipeline (tüm API'lar)
  - [ ] Her biri için:
    - [ ] Precision ölçüsü
    - [ ] Recall ölçüsü
    - [ ] F1 score
    - [ ] Execution time

- [ ] **Görev 4.3**: Sonuçları raporlama
  - [ ] JSON benchmark raporu
  - [ ] Grafik karşılaştırması
  - [ ] Tablo formatı

- [ ] **Çıktı**: `root_scripts/benchmark_suite.py`
  - [ ] Script yazılı
  - [ ] `trdizin_crossref_doi_stats_10k/benchmark_report.json`
  - [ ] Performance grafikleri

### Validation & QA
- [ ] **Görev 4.4**: Tüm FAZ'ları kontrol etme

#### FAZ 1 Validation
- [ ] Semantic Scholar entegre edilmiş
- [ ] Europe PMC entegre edilmiş
- [ ] API'lar stabil çalışıyor
- [ ] Başarı oranı artışı ölçülmüş (+3%)

#### FAZ 2 Validation
- [ ] Eşleşmeyen referanslar kategorize edilmiş
- [ ] 8 kategori tanımlanmış
- [ ] JSON + MD + CSV raporları oluşturulmuş
- [ ] Dashboard canlı ve güncellenen
- [ ] Görünürlük %100

#### FAZ 3 Validation
- [ ] Paralel işlem 4x+ hızlı
- [ ] Cache hit rate %80+
- [ ] Rate limiting hiç violated edilmemiş
- [ ] Monitoring metrikleri kaydedilmiş
- [ ] No memory leaks

#### FAZ 4 Validation
- [ ] Precision > 90%
- [ ] Recall > 70%
- [ ] F1 > 0.80
- [ ] Tüm benchmark sonuçları kaydedilmiş

### Final Results
- [ ] **Görev 4.5**: Sonuç raporu
  - [ ] Toplam başarı: 75%+ ✓
  - [ ] Başarı dağılımı:
    - [ ] Crossref: 58.26%
    - [ ] OpenAlex: %2-5 (hedef)
    - [ ] Semantic Scholar: %3-5 (hedef)
    - [ ] Europe PMC: %1-2 (hedef)
    - [ ] Diğer: %4-10 (existing)
  - [ ] Eşleşmeyen: %25 (hedef)
    - [ ] Kategorize: 100%
    - [ ] Insight: 8 kategori detayı

- [ ] **Görev 4.6**: Dökümentasyon
  - [ ] Tüm script'ler yorumlanmış
  - [ ] README'ler güncellenmiş
  - [ ] Usage examples eklenmiş
  - [ ] Architecture diagram (opsiyonel)

- [ ] **Çıktılar**:
  - [ ] `trdizin_crossref_doi_stats_10k/FINAL_REPORT.json`
  - [ ] `trdizin_crossref_doi_stats_10k/FINAL_REPORT.md`
  - [ ] Tüm grafikler PNG formatında

### Hafta 4 Finalı
- [ ] Benchmark tamamlandı ✅
- [ ] Validation başarılı ✅
- [ ] Başarı oranı hedefine ulaştı (75%+) ✅
- [ ] Dökümentasyon tamamlandı ✅

---

## 🎯 GENEL BAŞARI KRİTERLERİ

### Nihai Metrikleri

```json
{
  "başarı_metrikleri": {
    "toplam_referans": 10000,
    "başlangıç_başarısı": "64.10%",
    "hedef_başarısı": "75.00%+",
    "improvement": "+10.90%",
    
    "kaynak_dağılımı": {
      "crossref": "58.26%",
      "openalex": "%2-5",
      "semantic_scholar": "%3-5",
      "europe_pmc": "%1-2",
      "diğer": "%4-10"
    },
    
    "eşleşmeyen_analiz": {
      "toplam_kategorize": "3590",
      "kategorize_oran": "100%",
      "ana_kategoriler": 8,
      "görünürlük": "Tamamlanmış"
    },
    
    "performans": {
      "paralel_hızlılık": "4x+",
      "cache_hit_rate": "%80+",
      "processing_time_reduction": "75%"
    }
  }
}
```

### ✅ Kontrol Listesi Özeti

| Faz | Bileşen | Durum | Hedef | 
|-----|---------|-------|-------|
| 1 | Semantic Scholar | ⏳ | ✅ |
| 1 | Europe PMC | ⏳ | ✅ |
| 2 | Kategorize | ⏳ | ✅ |
| 2 | Dashboard | ⏳ | ✅ |
| 3 | Paralel İşlem | ⏳ | ✅ |
| 3 | Caching | ⏳ | ✅ |
| 3 | Monitoring | ⏳ | ✅ |
| 4 | Benchmark | ⏳ | ✅ |
| 4 | Validation | ⏳ | ✅ |
| **FINAL** | **Başarı Oranı** | **64.10%** | **75%+** |

---

## 📅 HAFTALIK İLERLEME

```
HAFTA 1: ⏳ [] [] [] [] []
         FAZ 1 - Yeni API'lar

HAFTA 2: ⏳ [] [] [] [] []
         FAZ 2 - Analiz & Dashboard

HAFTA 3: ⏳ [] [] [] [] []
         FAZ 3 - Performans

HAFTA 4: ⏳ [] [] [] [] []
         FAZ 4 - Doğrulama

HEDEF:   📊 75%+ başarı oranı
```

---

## 🚨 Kritik Noktalar

### Risk 1: API Rate Limiting
- **Olay**: Rate limit exceeded
- **Çözüm**: Cache mekanizması + politeness delay
- **Kontrol**: ✅ Hafta 3 test edilir

### Risk 2: Memory Issues (Paralel)
- **Olay**: Large dataset paralel işlem
- **Çözüm**: Chunk size ayarı + monitoring
- **Kontrol**: ✅ Hafta 3 test edilir

### Risk 3: Data Quality
- **Olay**: Eşleşmeler yanlış olabilir
- **Çözüm**: Manual validation sampling
- **Kontrol**: ✅ Hafta 4 benchmark ile ölçülür

### Risk 4: API Outage
- **Olay**: Bir API kapanır
- **Çözüm**: Fallback mekanizması
- **Kontrol**: ✅ Error handling tüm API'larda

---

## 📞 İLETİŞİM & SUPPORT

**Sorunlar Önerileri**:
1. Semantic Scholar rate limit → Politeness delay +1 sec
2. Cache disk space → `.cache/` boyutunu kontrol et
3. Parallel deadlock → Worker count düşür (8 → 4)
4. API connectivity → Network debug (`ping api.semanticscholar.org`)

**İletişim**:
- Teknik sorular: `root_scripts/README.md`
- Genel sorular: `ENTEGRASYON_REHBERI.md`
- Quick fixes: `HIZLI_BASLANGIC.md`

---

## ✨ İmza

**Başlangıç Tarihi**: 2026-08-14  
**Hedef Bitiş**: 2026-09-15  
**Proje Müdürü**: [AD SOYAD]  
**Status**: 🟡 Planning & Ready to Start  

```
Başlangıç Onayı:  ________________  Tarih: ___________
Tamamlanma Onayı: ________________  Tarih: ___________
```

---

**Bu kontrol listesi yazdırılabilir ve duvara asılabilir.** 📌

Haftalık ilerlemeyi işaretlemek için kutu kopyalayın:
- `⏳` = Devam Ediyor
- `✅` = Tamamlandı
- `❌` = Başarısız (nota ekle)
