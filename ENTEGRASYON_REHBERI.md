# TR Dizin Referans Eşleştirme - Kapsamlı Entegrasyon Rehberi

**Tarih**: 2026-08-14  
**Proje**: trdizin-reference-matching-bundle  
**Amaç**: Araştırma rehberini mevcut pipeline'a entegre etme

---

## 📊 MEVCUT DURUM ANALİZİ

### ✅ Zaten Uygulanmış (Rehberin Yöntemleri)

| Yöntem | Uygulama | Dosya | Durum |
|--------|----------|-------|-------|
| **Crossref DOI** | Deney 1 | `trdizin_crossref_doi_stats.py` | ✅ Aktif |
| **Crossref Bibliyografik** | Deney 2-3 | `trdizin_crossref_bibliographic_fallback.py` | ✅ Aktif |
| **OpenAlex API** | Deney 4,6 | `trdizin_openalex_fallback.py` | ✅ Aktif (API key) |
| **DataCite REST API** | Deney 5 | `trdizin_datacite_fallback.py` | ⚠️ Denendi (sıfır katkı) |
| **DergiPark OAI-PMH** | Deney 7 | `trdizin_dergipark_oai_fallback.py` | ✅ Aktif |
| **DergiPark Article Probe** | Deney 11 | `trdizin_dergipark_article_file_probe.py` | ✅ Aktif |
| **GROBID Reparse** | Deney 19 | `trdizin_experiment19_grobid_reparse_retry.py` | ✅ Aktif |
| **Fuzzy Matching** | Deney 20 | `trdizin_experiment20_fuzzy_matching.py` | ✅ Aktif |
| **YOK Tez Resolver** | Deney 21 | `trdizin_experiment21_yok_tez_resolver.py` | ✅ Aktif |
| **Google Scholar** | Browser/Selenium | `trdizin_google_scholar_*.py` | ✅ Aktif |
| **GROBID Training** | Özel | Root eğitim scripts | ✅ Özel pipeline |

### ⚠️ Kısmen Uygulanmış

| Yöntem | Durum | Açıklama |
|--------|-------|---------|
| **Eşleşmeyen Referans Analizi** | 🟡 Temel | Kategorize edilmiş, detay raporlar yok |
| **Rate Limiting & Monitoring** | 🟡 Manuel | Cache kullanılıyor, formal monitoring yok |
| **Pipeline Orchestration** | 🟡 Sequential | Sıralı, paralel işlem yok |
| **Result Validation** | 🟡 JSON/JSONL | Standart QA metriği yok |

### ❌ Eksik/Önerilir

| Yöntem | Rehbir | Uyarı |
|--------|--------|--------|
| **Semantic Scholar API** | ✓ | HTTP API mevcut, henüz entegre değil |
| **Europe PMC API** | ✓ | Biyomedikal kaynaklar için faydalı |
| **PubMed Central** | ✓ | Tıbbi referanslar için |
| **OpenRefine Integration** | ✓ | Web-tabanlı reconciliation |
| **R Stack Statistics** | ✓ | Python tercih edilmiş olabilir |
| **Citation.js Adapter** | ✓ | JavaScript kütüphanesi |

---

## 🎯 ENTEGRASYON STRATEJISI

### Faz 1: Eksik API Entegrasyonları (1-2 hafta)

#### 1.1 Semantic Scholar API
```python
# semanticscholar_fallback.py
import requests

class SemanticScholarResolver:
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    
    def search_paper(self, title, author=None, year=None):
        """
        Semantic Scholar paper search
        Daha hızlı yanıt, büyük döküman havuzu
        """
        params = {
            'query': title,
            'fields': 'title,authors,year,doi,venue,externalIds'
        }
        resp = requests.get(f"{self.BASE_URL}/paper/search", params=params)
        results = resp.json().get('data', [])
        
        # Eğer author/year var, filtreleme yap
        if author or year:
            results = self._filter_results(results, author, year)
        
        return results[0] if results else None
```

**Neden?** 
- Crossref'ten 5x daha hızlı
- Biyomedikal kaynaklar için kapsam geniş
- Ücretsiz API, rate limit: 100 req/5 dakika

**Uyuşma Threshold**: title similarity > 0.85

#### 1.2 Europe PMC API (Biyomedikal)
```python
# europepmc_fallback.py
def search_europepmc(reference_obj):
    """
    Biomedikal referanslar için PMC kaynakları
    PMID, PMCID buluyor
    """
    query = f"{reference_obj.get('title', '')} {reference_obj.get('author', '')}"
    resp = requests.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={
            'query': query,
            'format': 'json',
            'pageSize': 5
        }
    )
    results = resp.json().get('resultList', {}).get('result', [])
    return results
```

**Neden?**
- Tıbbi literatur için yüksek accuracy
- DOI ve PubMed ID mapping
- DergiPark tıp dergilerine katkı

#### 1.3 PubMed E-utilities (NCBI)
```python
# pubmed_fallback.py
def search_pubmed(title, author=None):
    """
    NCBI E-utilities ile PubMed araması
    """
    esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        'db': 'pubmed',
        'term': f'"{title}"[TIAB]',
        'format': 'json',
        'usehistory': 'y'
    }
    resp = requests.get(esearch_url, params=params)
    return resp.json()
```

---

### Faz 2: Veri Kalitesi & Analiz (2-3 hafta)

#### 2.1 Eşleşmeyen Referansları Kategorize Etme

Mevcut dosya: `trdizin_crossref_doi_stats_10k/unmatched_analysis.py` (YENİ)

```python
# unmatched_analysis.py
import pandas as pd
import json
from collections import Counter

def categorize_unmatched_references(results_file, final_output):
    """
    Son pipeline çıktısında "unmatched" olan referansları 
    türe göre kategorize et
    """
    
    results = pd.read_json(results_file, lines=True)
    unmatched = results[results['match_source'] == 'unmatched']
    
    categories = {
        'gri_edebiyat': [],
        'tezler': [],
        'konferans_islemleri': [],
        'yasal_patent': [],
        'eski_yayinlar': [],
        'turdish_kaynaklar': [],
        'ozel_koleksiyonlar': [],
        'diger': []
    }
    
    for idx, row in unmatched.iterrows():
        ref_text = str(row.get('original_reference', '')).lower()
        year = int(row.get('year', 2000)) if row.get('year') else 2000
        
        # Kategorize et
        if any(w in ref_text for w in ['report', 'teknik rapor', 'memorandum', 'çalışma']):
            categories['gri_edebiyat'].append(row)
        elif any(w in ref_text for w in ['tez', 'thesis', 'dissertation', 'doktora']):
            categories['tezler'].append(row)
        elif any(w in ref_text for w in ['conference', 'proceedings', 'konferans', 'bildiri']):
            categories['konferans_islemleri'].append(row)
        elif any(w in ref_text for w in ['law', 'legislation', 'yasal', 'patent', 'reg']):
            categories['yasal_patent'].append(row)
        elif year < 1990:
            categories['eski_yayinlar'].append(row)
        elif any(c.is_alpha() and ord(c) > 127 for c in str(row.get('title', ''))):
            categories['turdish_kaynaklar'].append(row)
        elif 'URL' in ref_text or 'website' in ref_text:
            categories['ozel_koleksiyonlar'].append(row)
        else:
            categories['diger'].append(row)
    
    # Rapor oluştur
    report = {
        'toplam_eslesmeyen': len(unmatched),
        'kategoriler': {k: len(v) for k, v in categories.items()},
        'yuzde_dagılımı': {
            k: round(len(v) / len(unmatched) * 100, 2) 
            for k, v in categories.items()
        },
        'detay': {
            k: [r.to_dict() for r in v[:10]]  # İlk 10 örnek
            for k, v in categories.items()
        }
    }
    
    with open(final_output, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    return report
```

#### 2.2 Pipeline İstatistikleri Dashboardi

`dashboard/reference_matching_stats.html` (YENİ)

```html
<!DOCTYPE html>
<html>
<head>
    <title>TR Dizin Referans Eşleştirme İstatistikleri</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { font-family: Arial; margin: 20px; }
        .metric { background: #f0f0f0; padding: 15px; margin: 10px 0; border-radius: 5px; }
        .chart { width: 100%; height: 400px; }
        h2 { color: #333; border-bottom: 2px solid #007bff; }
    </style>
</head>
<body>
    <h1>📊 TR Dizin Referans Eşleştirme Sonuçları</h1>
    
    <div class="metric">
        <h3>Genel Başarı Metrikleri</h3>
        <p>✅ <strong>Toplam Eşleşen:</strong> <span id="total-matched">0</span></p>
        <p>❌ <strong>Eşleşemeyen:</strong> <span id="total-unmatched">0</span></p>
        <p>📈 <strong>Başarı Oranı:</strong> <span id="success-rate">0%</span></p>
    </div>
    
    <div id="source-breakdown" class="chart"></div>
    <div id="category-breakdown" class="chart"></div>
    <div id="temporal-trend" class="chart"></div>
    
    <script>
        fetch('/api/stats')
            .then(r => r.json())
            .then(data => {
                document.getElementById('total-matched').textContent = data.total_matched;
                document.getElementById('total-unmatched').textContent = data.total_unmatched;
                document.getElementById('success-rate').textContent = 
                    ((data.total_matched / (data.total_matched + data.total_unmatched) * 100).toFixed(2)) + '%';
                
                // Kaynağa göre dağılım grafiği
                Plotly.newPlot('source-breakdown',
                    [{
                        x: data.sources.map(s => s.name),
                        y: data.sources.map(s => s.count),
                        type: 'bar'
                    }],
                    {title: 'Kaynağa Göre Eşleşme Sayısı'}
                );
            });
    </script>
</body>
</html>
```

---

### Faz 3: Pipeline Optimizasyonu (2 hafta)

#### 3.1 Paralel İşlem (Multiprocessing)

```python
# parallel_reference_matching.py
from multiprocessing import Pool
from functools import partial

class ParallelReferenceMatcher:
    def __init__(self, num_workers=8):
        self.num_workers = num_workers
    
    def match_references(self, references, methods=['crossref', 'openalex', 'dergipark']):
        """
        Referansları paralel olarak işle
        """
        with Pool(self.num_workers) as pool:
            matcher_func = partial(self._match_single, methods=methods)
            results = pool.map(matcher_func, references)
        
        return results
    
    def _match_single(self, ref, methods):
        """Tek referans için tüm yöntemleri dene"""
        result = {'reference': ref, 'matches': {}}
        
        for method in methods:
            try:
                match = self._execute_method(method, ref)
                if match:
                    result['matches'][method] = match
            except Exception as e:
                result['matches'][method] = {'error': str(e)}
        
        # En iyi match'i seç
        result['best_match'] = self._select_best_match(result['matches'])
        return result
```

#### 3.2 Rate Limiting & Caching

```python
# rate_limiter.py
import time
from functools import wraps
import diskcache

class RateLimitedAPI:
    def __init__(self, cache_dir, requests_per_second=10):
        self.cache = diskcache.Cache(cache_dir)
        self.requests_per_second = requests_per_second
        self.min_interval = 1 / requests_per_second
        self.last_request_time = {}
    
    def rate_limited(self, api_name):
        """Decorator for API calls"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                # Cache kontrolü
                cache_key = f"{api_name}:{args}:{kwargs}"
                if cache_key in self.cache:
                    return self.cache[cache_key]
                
                # Rate limit kontrol
                now = time.time()
                last_time = self.last_request_time.get(api_name, 0)
                elapsed = now - last_time
                
                if elapsed < self.min_interval:
                    time.sleep(self.min_interval - elapsed)
                
                # API çağrısı
                result = func(*args, **kwargs)
                self.last_request_time[api_name] = time.time()
                
                # Cache'e kaydet (1 gün)
                self.cache[cache_key] = result
                self.cache.expire(cache_key, 86400)
                
                return result
            
            return wrapper
        return decorator
```

#### 3.3 Monitoring & Logging

```python
# monitoring.py
import logging
import json
from datetime import datetime

class PipelineMonitor:
    def __init__(self, log_file):
        self.log_file = log_file
        self.stats = {
            'start_time': None,
            'processed': 0,
            'matched': 0,
            'api_calls': {},
            'errors': []
        }
    
    def log_match(self, reference_id, source, match_data):
        """Eşleşme etkinliğini kaydet"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'reference_id': reference_id,
            'source': source,
            'match_score': match_data.get('score'),
            'execution_time': match_data.get('exec_time')
        }
        
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        self.stats['matched'] += 1
        self.stats['api_calls'][source] = self.stats['api_calls'].get(source, 0) + 1
    
    def get_report(self):
        """İstatistik raporu oluştur"""
        elapsed = datetime.now() - self.stats['start_time']
        return {
            'toplam_islem': self.stats['processed'],
            'basarili_eslesme': self.stats['matched'],
            'basari_orani': self.stats['matched'] / self.stats['processed'] * 100,
            'sure': str(elapsed),
            'api_cagrilari': self.stats['api_calls'],
            'hatalar': self.stats['errors']
        }
```

---

### Faz 4: Sonlandırma & Doğrulama (1-2 hafta)

#### 4.1 Benchmark Suite

```python
# benchmark_suite.py
def benchmark_reference_matching():
    """
    Pipeline performans benchmarku
    
    Test kümesi: 1000 referans (çeşitli türler)
    Ölçütler:
    - Doğruluk (Precision/Recall)
    - Hız (saniye cinsinden)
    - API verimliliği
    """
    
    benchmarks = {
        'crossref_only': [],
        'crossref_openalex': [],
        'full_pipeline': [],
    }
    
    # Her config için test et
    # Sonuçları JSON'a kaydet
    # Grafikleri oluştur
    
    return benchmarks
```

#### 4.2 Validation Checklist

- [ ] Tüm API'lar çalışıyor mu?
- [ ] Rate limiting çalışıyor mu?
- [ ] Cache hit rate > 80%?
- [ ] Paralel işlem 4x+ hızlı?
- [ ] Eşleşmeyen referanslar kategorize edilmiş?
- [ ] İstatistik raporu oluşturulmuş?
- [ ] Dashbord canlı mi?

---

## 📋 DOSYA YAPISI (ÖNERİLEN)

```
root_scripts/
├── ENTEGRASYON_REHBERI.md (bu dosya)
├── AKSIYON_PLANI.md (detaylı görevler)
├── 
├── [MEVCUT DOSYALAR]
│
├── [FAZ 1 - YENİ DOSYALAR]
├── trdizin_semanticscholar_fallback.py
├── trdizin_europepmc_fallback.py
├── trdizin_pubmed_fallback.py
│
├── [FAZ 2 - ANALİZ DOSYALARI]
├── unmatched_reference_analysis.py
├── pipeline_statistics_reporter.py
│
├── [FAZ 3 - OPTİMİZASYON]
├── parallel_reference_matcher.py
├── rate_limiter_cache.py
├── pipeline_monitor.py
│
├── [FAZ 4 - DOĞRULAMA]
├── benchmark_suite.py
├── validation_checklist.txt
│
└── [YÜKSELTİLMİŞ DOSYALAR]
    ├── reference_matching_config.yaml (yapı dosyası)
    └── requirements.txt (güncellenmiş)
```

---

## 🔍 BAŞARILILIK ÖLÇÜTLERİ

### Hedefler

| Metrik | Mevcut | Hedef | Faz |
|--------|--------|-------|-----|
| **DOI Başarısı** | 18.55% | 20%+ | 1 |
| **Crossref Bibliyografik** | 56.07% | 62%+ | 2 |
| **OpenAlex Katkısı** | %0.2 | %5%+ | 1 |
| **Semantic Scholar** | Yok | %3%+ | 1 |
| **Toplam Pipeline** | 64.10% | 75%+ | 3 |
| **Eşleşmeyen Kategorize** | Temel | 100% | 2 |

### İzleme Göstergeleri

```python
def calculate_success_metrics(results):
    return {
        'total_references': len(results),
        'matched': len([r for r in results if r['match_source'] != 'unmatched']),
        'success_rate': matched / len(results) * 100,
        'crossref_share': len([r for r in results if r['match_source'] == 'crossref']) / matched * 100,
        'openalex_share': len([r for r in results if r['match_source'] == 'openalex']) / matched * 100,
        'unmatched_by_category': categorize_unmatched(results),
        'processing_time_seconds': get_elapsed_time(),
        'api_cost_estimate': calculate_api_costs(results)
    }
```

---

## 🚀 BAŞLANGICH ADIMI

1. **Faz 1: Semantic Scholar Entegrasyonu** (En yüksek ROI)
   - Implementation: 2 gün
   - Testing: 1 gün
   - Beklenen artış: %2-3

2. **Faz 2: Eşleşmeyen Analiz**
   - Implementation: 3 gün
   - İlişki: Faz 1'ü beklemez

3. **Faz 3: Paralel Processing**
   - Implementation: 3 gün
   - Performance beklentisi: 4x hızlı

**Toplam Zaman**: 3-4 hafta  
**Beklenen Sonuç**: 75%+ başarı oranı

---

## 📚 REFERANSLAR

- [Crossref API Docs](https://github.com/CrossRef/rest-api-doc)
- [OpenAlex API](https://docs.openalex.org/)
- [Semantic Scholar API](https://www.semanticscholar.org/product/api)
- [Europe PMC API](https://europepmc.org/api/)
- [GROBID Documentation](https://grobid.readthedocs.io/)

---

**Not**: Bu rehber mevcut projemizi maksimum başarıya ulaştırmak için tasarlanmıştır. Her faz bağımsız olarak değerlendirilebilir ve uygulanabilir.
