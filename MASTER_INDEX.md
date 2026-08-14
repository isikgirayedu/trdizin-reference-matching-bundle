# 📚 MASTER INDEX - Entegrasyon Rehberi Dosyaları

**Proje**: trdizin-reference-matching-bundle  
**Tarih**: 2026-08-14  
**Sürüm**: 1.0  

---

## 📖 Dokümantasyon Haritası

### 🎯 **0. BAŞLA BURADAN** (Bu Dosya)
📄 **Dosya**: `MASTER_INDEX.md`

Tüm dokümantasyonun hızlı referans indexi ve yönlendirmesi.

---

## 📋 Temel Dokümantasyon

### 1. 🚀 HIZLI_BASLANGIC.md
**İçerik**: 5 dakikalık başlama rehberi  
**Okuma Süresi**: 5 dakika  
**Hedef Kişi**: Proje yöneticisi, yeni developer  

**Ne Yapacaksın**:
- Projenin özeti
- İlk hafta görevleri
- Temel komutlar
- İstatistik beklentileri

**Kullan Eğer**: Hızlı bir overview istiyorsan

---

### 2. 📊 ENTEGRASYON_REHBERI.md
**İçelik**: Kapsamlı stratejik plan  
**Okuma Süresi**: 20 dakika  
**Hedef Kişi**: Proje lideri, teknik müdür  

**Ne Yapacaksın**:
- Mevcut durumun detaylı analizi
- 4 faz entegrasyon planı
- API entegrasyonları (Semantic Scholar, Europe PMC, vb)
- Başarı metrikleri ve hedefler
- Dosya yapısı önerileri

**Kullan Eğer**: Stratejik kararlar almak istiyorsan

---

### 3. 📋 AKSIYON_PLANI.md
**İçerik**: Hafta-hafta detaylı görev planı  
**Okuma Süresi**: 30 dakika  
**Hedef Kişi**: Developer, implementation team  

**Ne Yapacaksın**:
- Her görev için Python kod şablonları
- Haftalı zamanlama
- Test kontrol listeleri
- Quick start komutları
- Hata giderme ipuçları

**Kullan Eğer**: Kod yazarken rehber istiyor

---

### 4. 📦 REQUIREMENTS_UPDATE.md
**İçerik**: Kütüphane ve ortam kurulumu  
**Okuma Süresi**: 10 dakika  
**Hedef Kişi**: DevOps, system admin  

**Ne Yapacaksın**:
- Yeni kütüphaneler listesi
- Kurulum komutları
- Version uyumluluğu
- Docker setup
- Sorun giderme

**Kullan Eğer**: Python ortamını kurmak istiyorsan

---

### 5. 🎯 KAPSAMLI_OZET.md
**İçelik**: Rehbir vs. Proje karşılaştırması  
**Okuma Süresi**: 15 dakika  
**Hedef Kişi**: Analist, research team  

**Ne Yapacaksın**:
- Rehbirdeki yöntemler vs. mevcut uygulamalar
- Tablo formatında karşılaştırma
- Boşlukları tanımla
- Entegrasyon önerileri

**Kullan Eğer**: Proje kapsamını anlamak istiyorsan

---

### 6. ✅ KONTROL_LISTESI.md
**İçelik**: Yazdırılabilir görev izleme  
**Okuma Süresi**: 5 dakika (Hazırlık aşaması)  
**Hedef Kişi**: Tüm takım  

**Ne Yapacaksın**:
- 4 faz için detaylı kontrol listeleri
- Haftalık progress tracking
- KPI metrikleri
- Risk yönetimi

**Kullan Eğer**: İlerlemeyi takip etmek istiyorsan

---

## 🎯 NASIL KULLANACAKSINA GÖRE

### Senaryo 1: "Hemen başlamak istiyorum"
```
1. HIZLI_BASLANGIC.md → Adım 1-3 (30 min)
2. Terminal'de: pip install fuzzywuzzy diskcache
3. AKSIYON_PLANI.md → Görev 1.1 (kod yazma)
```

### Senaryo 2: "Yönetici/Müdür olarak karar almak istiyorum"
```
1. KAPSAMLI_OZET.md → Durum analizi
2. ENTEGRASYON_REHBERI.md → Stratejik plan
3. KONTROL_LISTESI.md → Resource planning
```

### Senaryo 3: "Developer olarak implementasyon yapacağım"
```
1. AKSIYON_PLANI.md → Hafta 1 görevleri
2. KAPSAMLI_OZET.md → Teknik detaylar
3. REQUIREMENTS_UPDATE.md → Ortam kurulumu
4. Kod şablonlarını kopyala ve adapt et
```

### Senaryo 4: "İlk kez çalışan takım"
```
1. HIZLI_BASLANGIC.md (Hepsi)
2. ENTEGRASYON_REHBERI.md (Bölüm 1-3)
3. KONTROL_LISTESI.md (Hafta 1)
4. AKSIYON_PLANI.md (Gerek duyduğunda)
```

---

## 📚 Dosya Hiyerarşisi

```
c:\Users\Şükran\trdizin-reference-matching-bundle\
│
├── 🎯 MASTER_INDEX.md (Bu dosya)
│   └── "Başlayan kişi buradan başlasın"
│
├── 🚀 HIZLI_BASLANGIC.md
│   └── "5 dakikalık genel bakış"
│
├── 📖 ENTEGRASYON_REHBERI.md
│   └── "Stratejik plan ve strateji"
│
├── 📋 AKSIYON_PLANI.md
│   └── "Detaylı görev ve kod şablonları"
│
├── 📦 REQUIREMENTS_UPDATE.md
│   └── "Kütüphane kurulumu"
│
├── 🎯 KAPSAMLI_OZET.md
│   └── "Rehbir vs. Proje karşılaştırması"
│
├── ✅ KONTROL_LISTESI.md
│   └── "Yazdırılabilir progress tracking"
│
├── [MEVCUT DOSYALARI]
├── README.md
├── CALISMA_RAPORU.md
├── BUNDLE_README.md
│
└── root_scripts/
    ├── [MEVCUT SCRIPTS]
    ├── trdizin_crossref_*.py
    ├── trdizin_experiment*.py
    │
    └── [YENİ OLACAK FAZ SCRIPTS]
        ├── trdizin_semanticscholar_fallback.py (Hafta 1)
        ├── trdizin_europepmc_fallback.py (Hafta 1)
        ├── unmatched_reference_analysis.py (Hafta 2)
        ├── parallel_reference_matcher.py (Hafta 3)
        ├── rate_limiter_cache.py (Hafta 3)
        ├── pipeline_monitor.py (Hafta 3)
        └── benchmark_suite.py (Hafta 4)
```

---

## 🔗 DOKÜMANLARDA BAĞLANTILAR

### HIZLI_BASLANGIC.md'de linkler:
- → AKSIYON_PLANI.md: Detaylı görevler
- → ENTEGRASYON_REHBERI.md: Stratejik plan
- → REQUIREMENTS_UPDATE.md: Paket kurulumu

### ENTEGRASYON_REHBERI.md'de linkler:
- → AKSIYON_PLANI.md: Faz detayları
- → KONTROL_LISTESI.md: Task tracking
- → KAPSAMLI_OZET.md: Proje analizi

### AKSIYON_PLANI.md'de linkler:
- → REQUIREMENTS_UPDATE.md: Paket kurulumu
- → ENTEGRASYON_REHBERI.md: Genel bakış
- → HIZLI_BASLANGIC.md: Quick start

### KAPSAMLI_OZET.md'de linkler:
- → ENTEGRASYON_REHBERI.md: Önerileri
- → KONTROL_LISTESI.md: Tracking
- → AKSIYON_PLANI.md: İmplementasyon

---

## 📊 HEDEFLER VE METRİKLER

### Başarı Kriteri (Tüm dokümanların amacı)

```
Başlangıç:  64.10% başarı oranı
Hedef:      75%+ başarı oranı
Süre:       4 hafta
```

### Faz Hedefleri

| Faz | Hafta | Çıktı | Hedef |
|-----|-------|-------|-------|
| 1 | 1 | Semantic Scholar + Europe PMC | +3% |
| 2 | 2 | Kategorize + Dashboard | Görünürlük |
| 3 | 3 | Paralel + Caching | 4x hızlı |
| 4 | 4 | Benchmark + Validation | 75%+ |

---

## 🎓 ÖĞRENME YOLU

Eğer referans matching'e yeni başlıyorsan:

1. **Gün 1**: HIZLI_BASLANGIC.md
   - Proje nedir anla
   - İlk komutları çalıştır

2. **Gün 2**: KAPSAMLI_OZET.md
   - Mevcut yöntemleri öğren
   - Eksikleri anla

3. **Gün 3**: ENTEGRASYON_REHBERI.md
   - Stratejik planı oku
   - Mimarıyı anla

4. **Gün 4+**: AKSIYON_PLANI.md
   - Kod yazmaya başla
   - Şablonları kullan

---

## 🆘 SSS - SÜRÜ SORULAN SORULAR

**S: Hangi dosyadan başlamalıyım?**  
C: Rolüne göre:
- Developer → AKSIYON_PLANI.md
- Manager → ENTEGRASYON_REHBERI.md
- DevOps → REQUIREMENTS_UPDATE.md
- Herkes → HIZLI_BASLANGIC.md

**S: İlk hafta neleri bitirmeliyim?**  
C: KONTROL_LISTESI.md'nin Faz 1 bölümüne bak.

**S: Kod şablonlarını nerede bulabilirim?**  
C: AKSIYON_PLANI.md'de her Görev altında Python kodu vardır.

**S: Başarı oranını nasıl takip edeceğim?**  
C: KONTROL_LISTESI.md ve KAPSAMLI_OZET.md'de KPI tabloları var.

**S: Risk olabilecekler neler?**  
C: KONTROL_LISTESI.md'nin "Kritik Noktalar" bölümüne bak.

---

## 🔄 VERSIYONLAMA

| Versiyon | Tarih | Değişiklikler |
|----------|-------|---------------|
| 1.0 | 2026-08-14 | İlk sürüm - 6 ana dokü |
| (Gelecek) | TBD | Haftalık güncellemeler |

---

## 📝 KAYIT VE NOTLAR

```
Project Name:    TR Dizin Reference Matching Bundle
Integration:     Research Guide → Project
Start Date:      2026-08-14
Target Deadline: 2026-09-15 (4 weeks)
Target Success:  75%+ matching rate

Documentation Set:
✅ MASTER_INDEX.md (Navigation)
✅ HIZLI_BASLANGIC.md (Quick Start)
✅ ENTEGRASYON_REHBERI.md (Strategy)
✅ AKSIYON_PLANI.md (Detailed Tasks)
✅ REQUIREMENTS_UPDATE.md (Setup)
✅ KAPSAMLI_OZET.md (Analysis)
✅ KONTROL_LISTESI.md (Tracking)

Status: Ready to Start 🚀
```

---

## 💬 İletişim & Desteği

**Bu dokümanlar hakkında soruların varsa**:

1. İlgili dosyayı yeniden oku (cevap orada olabilir)
2. KONTROL_LISTESI.md'nin "Risk" bölümünü kontrol et
3. AKSIYON_PLANI.md'nin "Sorun Giderme" bölümünü kontrol et
4. Yerel Python/Git topluluğuna danış

---

## ✨ TEŞEKKÜRLER

Bu kapsamlı rehber şu kaynakları kullanarak hazırlanmıştır:

- **Orijinal Araştırma Rehberi**: Referans eşleştirme metodolojileri
- **Mevcut Proje Analizi**: TR Dizin-reference-matching-bundle
- **Best Practices**: API entegrasyonu, pipeline oluşturma, performans optimizasyonu

---

**BAŞLAMAYA HAZIRSAN?**

👉 **Sonraki Adım**: HIZLI_BASLANGIC.md → Adım 1-2 (30 dakika)

---

**Hazırlayan**: GitHub Copilot  
**Şablon**: Integration Guide Template v1.0  
**Lisans**: Project-internal  

🎯 **Hedef**: 64% → 75%+ başarı oranı (4 hafta)
