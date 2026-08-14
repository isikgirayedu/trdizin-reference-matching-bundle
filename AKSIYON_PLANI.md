# Detaylı Aksiyon Planı - TR Dizin Referans Eşleştirme

**Hazırlandı**: 2026-08-14  
**Hedef**: 75%+ başarı oranına ulaşmak  
**Tahmini Süre**: 3-4 hafta

---

## 📅 FAZE WISE AKSIYON PLANI

### ⭐ FAZ 1: SEMANTIC SCHOLAR ENTEGRASYONU (Hafta 1)

**Neden Öncelikli?**
- Daha az bağımlılık (OpenAlex'ten farklı dataset)
- Daha hızlı API cevapları
- Yüksek doğruluk oranı
- ~2-3% ek başarı beklentisi

#### Görev 1.1: Semantic Scholar Fallback Modülü
**Dosya**: `root_scripts/trdizin_semanticscholar_fallback.py`  
**Süre**: 1 gün  
**Şablonu**:

```python
#!/usr/bin/env python3
"""
TR Dizin - Semantic Scholar Fallback Modülü
Crossref/OpenAlex'te bulunamayan referansları Semantic Scholar'da arıyor.
"""

import requests
import json
import time
from typing import Dict, List, Optional
from fuzzywuzzy import fuzz
from pathlib import Path

class SemanticScholarFallback:
    """
    Semantic Scholar API: https://api.semanticscholar.org/graph/v1
    Rate Limit: 100 req/5 min (no API key needed)
    """
    
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    TIMEOUT = 10
    MIN_TITLE_SIMILARITY = 0.80
    
    def __init__(self, cache_file=None):
        self.cache = {}
        self.cache_file = cache_file
        if cache_file and Path(cache_file).exists():
            self._load_cache()
    
    def search_paper(self, reference: Dict) -> Optional[Dict]:
        """
        Tek referansı Semantic Scholar'da ara
        """
        title = reference.get('title', '').strip()
        author = reference.get('author', '').strip()
        year = reference.get('year')
        
        if not title:
            return None
        
        # Cache kontrolü
        cache_key = f"ss:{title}:{author}:{year}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            # Basit arama
            params = {
                'query': f"{title} {author}",
                'fields': 'title,authors,year,doi,venue,externalIds',
                'limit': 5
            }
            
            resp = requests.get(
                f"{self.BASE_URL}/paper/search",
                params=params,
                timeout=self.TIMEOUT
            )
            
            if resp.status_code != 200:
                return None
            
            results = resp.json().get('data', [])
            
            if not results:
                self.cache[cache_key] = None
                return None
            
            # En iyi match'i seç
            best_match = self._select_best_match(title, author, year, results)
            
            if best_match:
                # Standart format'a dönüştür
                normalized = self._normalize_result(best_match)
                self.cache[cache_key] = normalized
                return normalized
            
            self.cache[cache_key] = None
            return None
            
        except Exception as e:
            print(f"[ERROR] SS API: {e}")
            return None
    
    def _select_best_match(self, title: str, author: str, year: Optional[int], 
                          results: List) -> Optional[Dict]:
        """
        Başlık benzerliği + yıl kontrolü ile en iyi match'i seç
        """
        scored_results = []
        
        for result in results:
            result_title = result.get('title', '')
            title_score = fuzz.token_set_ratio(title.lower(), result_title.lower())
            
            # Yıl kontrolü (opsiyonel)
            year_match = True
            if year and result.get('year'):
                year_diff = abs(int(result['year']) - year)
                year_match = year_diff <= 1  # ±1 yıl tolerans
            
            if title_score >= (self.MIN_TITLE_SIMILARITY * 100):
                scored_results.append({
                    'result': result,
                    'score': title_score,
                    'year_match': year_match
                })
        
        if not scored_results:
            return None
        
        # En yüksek skoru seç (yıl eşleşirse bonus puan)
        best = max(scored_results, key=lambda x: x['score'] + (10 if x['year_match'] else 0))
        
        return best['result'] if best['score'] > 80 else None
    
    def _normalize_result(self, ss_result: Dict) -> Dict:
        """
        Semantic Scholar sonucunu standart format'a dönüştür
        """
        return {
            'title': ss_result.get('title'),
            'authors': [a['name'] for a in ss_result.get('authors', [])],
            'year': ss_result.get('year'),
            'doi': ss_result.get('externalIds', {}).get('DOI'),
            'venue': ss_result.get('venue'),
            'external_ids': ss_result.get('externalIds', {}),
            'semantic_scholar_id': ss_result.get('paperId'),
            'match_confidence': 'high',
            'source': 'semantic_scholar'
        }
    
    def _save_cache(self):
        """Cache'i dosyaya kaydet"""
        if self.cache_file:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f)
    
    def _load_cache(self):
        """Cache dosyasından yükle"""
        if self.cache_file and Path(self.cache_file).exists():
            with open(self.cache_file, 'r') as f:
                self.cache = json.load(f)


def main():
    """
    Örnek kullanım
    """
    import sys
    
    if len(sys.argv) < 2:
        print("Kullanım: python3 trdizin_semanticscholar_fallback.py <input_jsonl> <output_jsonl>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "semanticscholar_fallback_results.jsonl"
    
    fallback = SemanticScholarFallback(cache_file="semanticscholar_cache.json")
    
    matched_count = 0
    total_count = 0
    
    with open(input_file, 'r') as infile, open(output_file, 'w') as outfile:
        for line in infile:
            total_count += 1
            ref = json.loads(line.strip())
            
            result = fallback.search_paper(ref)
            
            output_record = {
                'reference_id': ref.get('id'),
                'original_reference': ref.get('reference'),
                'semantic_scholar_result': result,
                'found': result is not None
            }
            
            if result:
                matched_count += 1
            
            outfile.write(json.dumps(output_record, ensure_ascii=False) + '\n')
            
            if total_count % 100 == 0:
                print(f"[Progress] {total_count} işlendi, {matched_count} eşleşti")
    
    fallback._save_cache()
    
    print(f"\n✅ Tamamlandı!")
    print(f"Toplam: {total_count}")
    print(f"Eşleşen: {matched_count}")
    print(f"Başarı: {matched_count/total_count*100:.2f}%")


if __name__ == '__main__':
    main()
```

**Kontrol Listesi**:
- [ ] Script yazıldı
- [ ] Test edildi (100 referansla)
- [ ] Cache mekanizması çalışıyor
- [ ] Rate limiting kontrol edildi
- [ ] Sonuçlar `trdizin_crossref_doi_stats_10k/semanticscholar_fallback/` klasöründe kaydedildi

#### Görev 1.2: Europe PMC Entegrasyonu
**Dosya**: `root_scripts/trdizin_europepmc_fallback.py`  
**Süre**: 1 gün

```python
#!/usr/bin/env python3
"""
Europe PMC Fallback - Biyomedikal Referanslar
"""

class EuropePMCFallback:
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    
    def search_paper(self, reference: Dict) -> Optional[Dict]:
        """
        Europe PMC'de biyomedikal referans ara
        """
        title = reference.get('title', '').strip()
        
        try:
            params = {
                'query': title,
                'format': 'json',
                'pageSize': 1,
                'sort': 'RELEVANCE'
            }
            
            resp = requests.get(self.BASE_URL, params=params, timeout=10)
            
            if resp.status_code != 200 or resp.json()['hitCount'] == 0:
                return None
            
            result = resp.json()['resultList']['result'][0]
            
            return {
                'title': result.get('title'),
                'pmid': result.get('pmid'),
                'pmcid': result.get('pmcid'),
                'doi': result.get('doi'),
                'source': 'europe_pmc'
            }
        except Exception as e:
            return None
```

**Kontrol Listesi**:
- [ ] Script yazıldı
- [ ] Test edildi (tıbbi referanslar)
- [ ] PMID/PMCID çıkarma çalışıyor
- [ ] Sonuçlar kaydedildi

---

### 🔍 FAZ 2: ESLESMEYEN REFERANSLARI ANALIZ (Hafta 2)

#### Görev 2.1: Eşleşmeyen Referans Kategorize Modülü
**Dosya**: `root_scripts/unmatched_reference_analysis.py`  
**Süre**: 2 gün

```python
#!/usr/bin/env python3
"""
Eşleşmeyen Referansları Kategorize Et
"""

import json
import re
from collections import Counter
from pathlib import Path

class UnmatchedAnalyzer:
    """
    Pipeline'ın son çıktısında "unmatched" referansları kategorize et
    """
    
    CATEGORIES = {
        'gri_edebiyat': {
            'keywords': ['report', 'teknik rapor', 'memorandum', 'çalışma', 'rapor', 'raporunun'],
            'description': 'Gri Edebiyat (Rapor, Teknik Belge, Memorandum)'
        },
        'tezler': {
            'keywords': ['tez', 'thesis', 'dissertation', 'doktora', 'yüksek lisans', 'phd', 'master'],
            'description': 'Akademik Tezler'
        },
        'konferans': {
            'keywords': ['conference', 'proceedings', 'konferans', 'bildiri', 'workshop', 'seminar'],
            'description': 'Konferans İşlemleri ve Bildirileri'
        },
        'yasal_patent': {
            'keywords': ['law', 'legislation', 'yasal', 'patent', 'reg', 'standart', 'iso'],
            'description': 'Yasal Dokümanlar ve Patentler'
        },
        'eski_yayinlar': {
            'date_range': (None, 1985),
            'description': 'Eski Yayınlar (1985 öncesi)'
        },
        'turk_kaynaklar': {
            'keywords': ['türk', 'kuran', 'hadis', 'quran', 'siyer'],
            'description': 'Türkçe ve Dini Kaynaklar'
        },
        'web_kaynaklar': {
            'keywords': ['website', 'url', 'blog', 'forum', 'www', '.com', '.org', '.edu'],
            'description': 'Web-tabanlı Kaynaklar ve Sosyal Medya'
        },
        'ozel_koleksiyonlar': {
            'keywords': ['archive', 'collection', 'library', 'koleksiyon', 'arşiv', 'kütüphane'],
            'description': 'Özel Koleksiyonlar ve Arşivler'
        }
    }
    
    def categorize(self, reference: Dict) -> str:
        """
        Referansı kategorize et
        """
        title = str(reference.get('title', '')).lower()
        author = str(reference.get('author', '')).lower()
        year = reference.get('year')
        ref_text = str(reference.get('original_reference', '')).lower()
        
        # Kombinatif text
        combined_text = f"{title} {author} {ref_text}"
        
        # Tarih kontrolü
        if year and year < 1985:
            return 'eski_yayinlar'
        
        # Keyword eşleştirmesi
        for cat_name, cat_info in self.CATEGORIES.items():
            if cat_name == 'eski_yayinlar':
                continue  # Zaten kontrol ettik
            
            if 'keywords' in cat_info:
                for keyword in cat_info['keywords']:
                    if keyword.lower() in combined_text:
                        return cat_name
        
        # Türkçe karakter kontrolü
        if any(ord(c) > 127 for c in title):
            return 'turk_kaynaklar'
        
        return 'diger'
    
    def analyze_file(self, input_file: str, output_dir: str = "unmatched_analysis"):
        """
        Tüm unmatched referansları analiz et
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(exist_ok=True)
        
        categories = {cat: [] for cat in self.CATEGORIES.keys()}
        categories['diger'] = []
        
        total_unmatched = 0
        
        print("📊 Eşleşmeyen Referansları Analiz Ediliyor...")
        
        with open(input_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                ref = json.loads(line.strip())
                
                # Sadece unmatched referansları al
                if ref.get('match_source') == 'unmatched':
                    total_unmatched += 1
                    category = self.categorize(ref)
                    categories[category].append({
                        'id': ref.get('id'),
                        'title': ref.get('title'),
                        'author': ref.get('author'),
                        'year': ref.get('year'),
                        'original': ref.get('original_reference', '')[:200]
                    })
                
                if line_num % 1000 == 0:
                    print(f"  ✓ {line_num} satır işlendi")
        
        # Raporları oluştur
        summary = {
            'toplam_eslesmeyen': total_unmatched,
            'kategoriler': {},
            'ortalama_yil_by_category': {},
            'ornekler': {}
        }
        
        for cat_name, items in categories.items():
            summary['kategoriler'][cat_name] = {
                'count': len(items),
                'yuzde': round(len(items) / total_unmatched * 100, 2) if total_unmatched > 0 else 0,
                'aciklama': self.CATEGORIES.get(cat_name, {}).get('description', 'Bilinmiyor')
            }
            
            # İlk 10 örneği kaydet
            summary['ornekler'][cat_name] = items[:10]
            
            # Ortalama yıl hesapla
            years = [item['year'] for item in items if item['year']]
            if years:
                summary['ortalama_yil_by_category'][cat_name] = sum(years) / len(years)
        
        # JSON raporu
        report_file = output_dir / "unmatched_analysis.json"
        with open(report_file, 'w') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        # Markdown raporu
        md_file = output_dir / "unmatched_analysis.md"
        self._write_markdown_report(summary, md_file)
        
        # Kategorilere göre CSV dosyaları
        for cat_name, items in categories.items():
            if items:
                import csv
                cat_file = output_dir / f"unmatched_{cat_name}.csv"
                with open(cat_file, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['id', 'title', 'author', 'year', 'original'])
                    writer.writeheader()
                    writer.writerows(items)
        
        print(f"\n✅ Analiz Tamamlandı!")
        print(f"Raporlar: {output_dir}/")
        
        return summary
    
    def _write_markdown_report(self, summary, output_file):
        """Markdown formatında rapor yaz"""
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# Eşleşmeyen Referanslar Analiz Raporu\n\n")
            f.write(f"**Toplam Eşleşmeyen**: {summary['toplam_eslesmeyen']}\n\n")
            
            f.write("## Kategoriye Göre Dağılım\n\n")
            f.write("| Kategori | Sayı | Yüzde | Açıklama |\n")
            f.write("|----------|------|-------|----------|\n")
            
            for cat_name, cat_info in summary['kategoriler'].items():
                f.write(f"| {cat_name} | {cat_info['count']} | "
                       f"{cat_info['yuzde']}% | {cat_info['aciklama']} |\n")
            
            f.write("\n## Kategori Örnekleri\n\n")
            
            for cat_name, examples in summary['ornekler'].items():
                if examples:
                    f.write(f"### {cat_name}\n\n")
                    for ex in examples[:3]:
                        f.write(f"- **{ex['title']}** ({ex['author']}, {ex['year']})\n")
                    f.write("\n")


def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Kullanım: python3 unmatched_reference_analysis.py <results_file> [output_dir]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "unmatched_analysis"
    
    analyzer = UnmatchedAnalyzer()
    analyzer.analyze_file(input_file, output_dir)


if __name__ == '__main__':
    main()
```

**Kontrol Listesi**:
- [ ] Script yazıldı
- [ ] Kategoriler test edildi
- [ ] Raporlar oluşturuluyor (JSON, MD, CSV)
- [ ] Sonuç analiz edildi

#### Görev 2.2: İstatistik Dashboardi
**Dosya**: `github_dashboard/reference_stats.html`  
**Süre**: 1 gün

(HTML/JavaScript kodu ile interaktif grafik)

**Kontrol Listesi**:
- [ ] HTML yazıldı
- [ ] Grafikler Plotly ile oluşturuluyor
- [ ] Canlı veri bağlantısı çalışıyor
- [ ] Dashboard erişilebilir

---

### ⚡ FAZ 3: PIPELINE OPTİMİZASYONU (Hafta 3)

#### Görev 3.1: Paralel İşlem
**Dosya**: `root_scripts/parallel_reference_matcher.py`  
**Süre**: 1.5 gün

```python
#!/usr/bin/env python3
"""
Paralel Referans Eşleştirme
Multiprocessing ile 4x+ hızlılık
"""

from multiprocessing import Pool, Manager
import json
from functools import partial

class ParallelReferenceMatcher:
    def __init__(self, num_workers=8):
        self.num_workers = num_workers
    
    def process_batch(self, references_file, methods=['crossref', 'openalex', 'semanticscholar']):
        """
        Referansları paralel olarak işle
        """
        # Referansları yükle
        references = []
        with open(references_file, 'r') as f:
            for line in f:
                references.append(json.loads(line.strip()))
        
        print(f"📊 {len(references)} referans paralel olarak işleniyor ({self.num_workers} worker)...")
        
        # Worker fonksiyonu oluştur
        worker_func = partial(self._match_single_reference, methods=methods)
        
        # Paralel işlemle
        with Pool(self.num_workers) as pool:
            results = pool.map(worker_func, references, chunksize=100)
        
        return results
    
    @staticmethod
    def _match_single_reference(reference, methods):
        """
        Tek referansı tüm yöntemlerle eşleştir
        """
        result = {
            'reference_id': reference.get('id'),
            'title': reference.get('title'),
            'matches': {}
        }
        
        # Farklı API'lardan sonuçları toplayın
        # ...
        
        return result
```

**Kontrol Listesi**:
- [ ] Multiprocessing script yazıldı
- [ ] Worker pool konfigürasyonu
- [ ] Çıktı dosyasına yazma paralel
- [ ] Performans testi yapıldı (4x+ hızlılık doğrulandı)

#### Görev 3.2: Caching & Rate Limiting
**Dosya**: `root_scripts/rate_limiter_cache.py`  
**Süre**: 1 gün

**Kontrol Listesi**:
- [ ] Cache sistem kuruldu (diskcache veya Redis)
- [ ] Rate limiting mekanizması
- [ ] Hit rate > 80% doğrulandı
- [ ] TTL (Time to Live) konfigürasyonu

#### Görev 3.3: Monitoring & Logging
**Dosya**: `root_scripts/pipeline_monitor.py`  
**Süre**: 1 gün

**Kontrol Listesi**:
- [ ] Logging mekanizması kuruldu
- [ ] Real-time metrikler (processed, matched, errors)
- [ ] API call trackingi
- [ ] Performans raporu

---

### ✅ FAZ 4: DOĞRULAMA VE FİNAL (Hafta 4)

#### Görev 4.1: Benchmark Suite
**Dosya**: `root_scripts/benchmark_suite.py`  
**Süre**: 1.5 gün

```python
def run_comprehensive_benchmark():
    """
    1000 referans üzerinde tüm yöntemleri test et
    """
    
    test_sets = {
        'doi_rich': load_references_with_doi(200),
        'doi_poor': load_references_without_doi(300),
        'medical': load_medical_references(200),
        'old_publications': load_old_references(100),
        'turkish_sources': load_turkish_references(200)
    }
    
    benchmark_results = {}
    
    for set_name, references in test_sets.items():
        print(f"\n🧪 Benchmark: {set_name}")
        
        results = {
            'crossref': time_and_measure(run_crossref, references),
            'crossref_openalex': time_and_measure(run_crossref_openalex, references),
            'full_pipeline': time_and_measure(run_full_pipeline, references),
        }
        
        benchmark_results[set_name] = results
    
    # Rapor oluştur
    save_benchmark_report(benchmark_results)
    
    return benchmark_results
```

**Kontrol Listesi**:
- [ ] Benchmark suite yazıldı
- [ ] 5 test seti hazırlandı
- [ ] Precision/Recall/F1 hesaplandı
- [ ] Grafikleri oluşturuldu

#### Görev 4.2: Final Validation
**Dosya**: `root_scripts/VALIDATION_CHECKLIST.txt`  
**Süre**: 1 gün

```
VALIDATION CHECKLIST - TR Dizin Reference Matching
===================================================

[ ] FAZ 1: API ENTEGRASYONLARI
  [x] Crossref (mevcut)
  [x] OpenAlex (mevcut)
  [ ] Semantic Scholar (YENİ)
  [ ] Europe PMC (YENİ)
  [ ] PubMed (Optional)

[ ] FAZ 2: ANALIZ VE RAPORLAMA
  [ ] Eşleşmeyen kategoriler tanımlandı
  [ ] 8 ana kategori belirlenmiş
  [ ] JSON + MD + CSV raporları oluşturuldu
  [ ] Dashboard canlı

[ ] FAZ 3: PERFORMANS
  [ ] Paralel işlem çalışıyor (4x+ hızlı)
  [ ] Caching aktif (%80+ hit rate)
  [ ] Rate limiting çalışıyor
  [ ] Logging sistemi aktif

[ ] FAZ 4: DOĞRULAMA
  [ ] Benchmark suite çalıştırıldı
  [ ] Precision > 90%
  [ ] Recall > 70%
  [ ] İstatistikler kaydedildi

[ ] ÖNCELİKLER
  [ ] Başarı oranı hedefine ulaştı (75%+)
  [ ] Eşleşme kaynakları dengeli
  [ ] Belgeleme tamamlandı
  [ ] Kod review yapıldı

[ ] DEPLOYMENT
  [ ] Production'a hazır
  [ ] Monitoring aktif
  [ ] Fallback mekanizmaları çalışıyor
```

---

## 🎯 HAFTALI ZAMANLANDıRMA

### Hafta 1: FAZ 1 - Yeni API'lar
- **Pazartesi-Salı**: Semantic Scholar modülü (100 ref test)
- **Çarşamba-Perşembe**: Europe PMC modülü (50 ref test)
- **Cuma**: İntegrasyon testi ve cache setup

**Çıktı**: +2-3% başarı oranı

### Hafta 2: FAZ 2 - Analiz
- **Pazartesi-Salı**: Unmatched kategorize sistemi
- **Çarşamba**: Raporlama (JSON, MD, CSV)
- **Perşembe-Cuma**: Dashboard oluşturma

**Çıktı**: Eşleşmeyen referansların türü belirlenmiş, grafikleri hazır

### Hafta 3: FAZ 3 - Optimizasyon
- **Pazartesi-Salı**: Paralel işlem (multiprocessing)
- **Çarşamba-Perşembe**: Caching + Rate Limiting
- **Cuma**: Monitoring sistemi

**Çıktı**: 4x hızlılık, 80%+ cache hit rate

### Hafta 4: FAZ 4 - Doğrulama
- **Pazartesi-Çarşamba**: Benchmark suite
- **Perşembe**: Final validation + rapor
- **Cuma**: Dokumentasyon ve review

**Çıktı**: 75%+ başarı oranı, tüm metrikler kaydedilmiş

---

## 📊 KPI İZLEME

```json
{
  "başarı_metrikleri": {
    "toplam_referans": 10000,
    "hedef_eslesme": 7500,
    "crossref_katkı": "58.26%",
    "openalex_katkı": "%0.2",
    "semantic_scholar_katkı": "hedef: %3",
    "toplam_hedef": "75%+",
    "tamamlama_tarihi": "2026-09-15"
  }
}
```

---

## 🚀 QUICK START KOMUTLARI

```bash
# Faz 1: Semantic Scholar
cd root_scripts/
python3 trdizin_semanticscholar_fallback.py \
  ../trdizin_crossref_doi_stats_10k/unmatched_references.jsonl \
  ../trdizin_crossref_doi_stats_10k/semanticscholar_fallback/results.jsonl

# Faz 2: Analiz
python3 unmatched_reference_analysis.py \
  ../trdizin_crossref_doi_stats_10k/combined_results.jsonl \
  ../trdizin_crossref_doi_stats_10k/analysis/

# Faz 3: Paralel İşlem
python3 parallel_reference_matcher.py \
  --input ../trdizin_crossref_doi_stats_10k/all_references.jsonl \
  --workers 8 \
  --output ../trdizin_crossref_doi_stats_10k/parallel_results/

# Faz 4: Benchmark
python3 benchmark_suite.py \
  --output ../trdizin_crossref_doi_stats_10k/benchmark_report.json
```

---

## 📞 İLETİŞİM VE SUPPORT

**Sorular/Sorunlar**:
1. Semantic Scholar API rate limit → Politeness delay 1 saniye
2. Cache size → SQLite: 500MB limit, eksik çıktı → temizle
3. Paralel deadlock → Worker process sınırını 8'e düşür

---

**Son Güncelleme**: 2026-08-14  
**Sorumlu**: TR Dizin Araştırma Takımı  
**Bütçe**: ~150 API credit (Semantic Scholar free, Europe PMC free)
