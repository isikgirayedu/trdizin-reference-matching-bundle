# Python Kütüphaneleri - Güncelleme Rehberi

## Mevcut requirements.txt Durumu
```
beautifulsoup4==4.14.3
datasette==0.65.3
Flask==3.0.3
playwright==1.62.0
requests==2.32.3
selenium==4.46.0
urllib3==2.7.0
```

## Önerilen Eklemeler (FAZ 1-4)

### Temel Bağımlılıklar (Zorunlu)
```bash
# String benzerliği (fuzzy matching)
fuzzywuzzy==0.18.0
python-Levenshtein==0.21.1

# Caching mekanizması
diskcache==5.6.3

# Paralel işlem
multiprocess==0.70.15
```

### Veri İşleme
```bash
# Pandas için veri manipülasyonu
pandas==2.1.0

# JSON işlemleri
ujson==5.8.0
```

### İstatistik ve Visualizasyon
```bash
# Grafik oluşturma
plotly==5.17.0
matplotlib==3.8.0

# İstatistik
numpy==1.24.0
scipy==1.11.0
```

### Logging ve Monitoring
```bash
# Advanced logging
python-json-logger==2.0.7

# Timing utilities
tenacity==8.2.3
```

### Opsiyonel (İleri Seviye)
```bash
# Redis caching (eğer distributed caching istiyorsan)
redis==5.0.0

# Profiling
memory-profiler==0.61.0
line-profiler==4.1.1
```

## Kurulum Komutları

### Güvenli Güncelleme (Mevcut Bağımlılıkları Koru)
```bash
# Var olan paketleri listele
pip freeze > current_requirements.txt

# Yeni paketleri ekle (birer birer test et)
pip install fuzzywuzzy python-Levenshtein diskcache
pip install plotly
pip install python-json-logger
```

### Tam Güncelleme (Önerilir)
```bash
# Güncellenmiş requirements.txt'i kullan
pip install -r requirements_updated.txt
```

## requirements_updated.txt

```
# Browser Automation & Web Scraping
beautifulsoup4==4.14.3
playwright==1.62.0
selenium==4.46.0

# Web Framework
Flask==3.0.3

# HTTP & Networking
requests==2.32.3
urllib3==2.7.0
tenacity==8.2.3

# String Processing & Matching
fuzzywuzzy==0.18.0
python-Levenshtein==0.21.1

# Data Processing
pandas==2.1.0
ujson==5.8.0
numpy==1.24.0
scipy==1.11.0

# Caching & Storage
diskcache==5.6.3
datasette==0.65.3

# Visualization
plotly==5.17.0
matplotlib==3.8.0

# Logging & Monitoring
python-json-logger==2.0.7

# Optional for Parallel Processing
multiprocess==0.70.15
```

## Kurulum Testi

```bash
# Tüm paketleri test et
python3 -c "
import requests
import fuzzywuzzy
import diskcache
import plotly
import pandas
print('✅ Tüm paketler başarıyla yüklendi!')
"
```

## İşletim Sistemi Gereksinimleri

### Windows
```bash
# Visual C++ build tools gerekebilir
# https://visualstudio.microsoft.com/visual-cpp-build-tools/
```

### macOS
```bash
# Xcode command line tools
xcode-select --install
```

### Linux
```bash
# Build essentials
sudo apt-get install build-essential python3-dev
```

## Hızlı Kurulum Script

```bash
#!/bin/bash
# setup_environment.sh

echo "🔧 TR Dizin Reference Matching - Ortam Kurulumu"

# Python versiyonu kontrolü
python3 --version || { echo "❌ Python 3 gerekli"; exit 1; }

# Mevcut ortamı yedekle
pip freeze > requirements_backup_$(date +%Y%m%d).txt
echo "✅ Backup: requirements_backup_$(date +%Y%m%d).txt"

# Güncelleme
echo "📦 Paketleri güncelleniyor..."
pip install --upgrade pip

# Yeni paketleri kur
pip install -r requirements_updated.txt

echo "✅ Kurulum tamamlandı!"
pip freeze | wc -l | xargs echo "📊 Toplam paket sayısı:"
```

## Versiyon Uyumluluğu

| Paket | Version | Python | Uyumluluk |
|-------|---------|--------|-----------|
| requests | 2.32.3 | 3.7+ | ✅ |
| pandas | 2.1.0 | 3.9+ | ✅ |
| plotly | 5.17.0 | 3.6+ | ✅ |
| selenium | 4.46.0 | 3.7+ | ✅ |
| fuzzywuzzy | 0.18.0 | 2.7+ | ✅ |
| diskcache | 5.6.3 | 3.6+ | ✅ |

## Sorun Giderme

### ImportError: No module named 'fuzzywuzzy'
```bash
pip install fuzzywuzzy python-Levenshtein --no-cache-dir
```

### Wheel build hatası
```bash
pip install --upgrade setuptools wheel
pip install -r requirements_updated.txt
```

### Uzun kurulum süresi
```bash
# Parallel kurulum (pip>=21.0)
pip install -r requirements_updated.txt --use-deprecated=legacy-resolver
```

### Version conflict
```bash
# Bağımlılıkları kontrol et
pip check

# Conflict varsa, eski paketi kaldır
pip uninstall <conflicting-package>
pip install <package>==<compatible-version>
```

## İleri Kurulum: Docker

```dockerfile
# Dockerfile
FROM python:3.14-slim

WORKDIR /app

COPY requirements_updated.txt .
RUN pip install --no-cache-dir -r requirements_updated.txt

COPY root_scripts/ ./root_scripts/
COPY trdizin_crossref_doi_stats_10k/ ./trdizin_crossref_doi_stats_10k/

CMD ["/bin/bash"]
```

Kullanım:
```bash
docker build -t trdizin-ref-matching .
docker run -it trdizin-ref-matching python3 root_scripts/trdizin_semanticscholar_fallback.py
```

---

**Not**: requirements_updated.txt'i mevcut requirements.txt ile değiştirmeden önce, tüm paketleri test etmenizi önerim.
