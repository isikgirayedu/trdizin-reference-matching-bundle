# TR Dizin Referans Eşleşmesini İyileştirme Planı

## Özet

- Mevcut strict toplam: `6124 / 10000 = 61.24%`.
- Plato nedeni: kalan referansların büyük kısmı DOI beklenmeyen kitap/web/tez/rapor türleri veya zayıf parse; aynı Crossref/OpenAlex sorgusunu gevşetmek false-positive üretir.
- Ana metrikler:
  - `strict_doi_resolved`: DOI bulunup Crossref ile doğrulananlar.
  - `strict_auto_resolved`: DOI olmasa bile TR Dizin/OpenAlex/DergiPark/PMID/ISBN gibi güvenli ID ile çözülenler.
  - `review_candidates`: otomatik sayıma girmeyen şüpheli adaylar.

## Uygulama

- Deney 12: `metadata.references[].targetPublication` alanını kullanarak TR Dizin iç referans resolver çalıştır.
- Deney 13: parser kodunu ortaklaştırıp title, author surname, year, journal, volume, issue, page, DOI, URL ve ISBN çıkar.
- Deney 14: OpenAlex sorgularını parsed article-like kalanlarla sınırla; API key sadece env değişkeninden okunur.
- Deney 15: DergiPark/OAI metadata indeksini journalCode, ISSN/eISSN ve dergi adı ile genişlet.
- Deney 16: hidden DOI, ISBN, kitap, web, tez ve rapor türlerini ayrı resolver ve ayrı metrikle işle.

## Çıktı

- Her deney için `*_matches.csv/jsonl`, `*_summary.json`, `*_report_tr.md`, `*_review_candidates.csv`.
- Dashboard'da iki çizgi:
  - Crossref DOI strict.
  - All strict resolved.
- DataCite Deney 5 tarihsel olarak kalır, yeni pipeline base'i Deney 11 + Deney 12 olur.

## Test Planı

- DOI normalize testleri: boşluklu DOI, `doi. org/`, trailing punctuation, `http://dx.doi.org/`.
- False-positive regression: Deney 8'de yanlış eşleşmeye açık örnekler strict'e girmemeli.
- Deney 12 smoke: 10 `targetPublication` kaydı fetch edilmeli, target ID metadata ID ile aynı olmalı.
- Birleşik sayım: aynı `sample_index` birden fazla deneyde bulunursa sadece bir kez sayılmalı.
- Dashboard: `node --check crossref_stats_dashboard/app.js`.

## Varsayımlar

- Ana başarı metriği `Strict kalite`.
- Broad adaylar raporlanır ama ana yüzdeye eklenmez.
- API anahtarları env değişkenlerinden gelir; raporlara yazılmaz.
- API rate limit durumunda cache + resume ile devam edilir, eşik gevşetilmez.
