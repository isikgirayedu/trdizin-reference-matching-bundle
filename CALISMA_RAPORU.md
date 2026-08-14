# TR Dizin Referans DOI / Kaynak Eslestirme Calisma Raporu

Bu rapor, bu sohbet boyunca yapilan TR Dizin referans eslestirme calismasinin
tek dosyalik ozetidir. Bundle klasoru:

```text
trdizin_reference_matching_bundle_2026-08-07/
```

Orijinal workspace dosyalari tasinmadi; bu bundle bir kopya/snapshot olarak
hazirlandi.

## Amac

TR Dizin kaynakli referanslarin DOI veya guvenilir kaynak kaydi ile ne kadar
eslestirilebildigini olcmek, Crossref disinda ek kaynaklarla eslesme oranini
artirmak ve kalan eslesmeyen referanslarin neden eslesmedigini analiz etmek.

Calismanin ana sorulari:

- Referanslarda DOI var mi?
- DOI varsa Crossref `works/{doi}` ile bulunuyor mu?
- DOI yoksa baslik, yazar, yil, dergi gibi bibliyografik alanlarla Crossref'te
  bulunabiliyor mu?
- Crossref disinda OpenAlex, DataCite, DergiPark, Europe PMC, PubMed, GROBID ve
  Google Scholar gibi kaynaklar ek eslesme sagliyor mu?
- Kalan eslesmeyen referanslar hangi turlerde yogunlasiyor?

## Veri Kapsami

Ana orneklem:

- Kaynak: `root_inputs/veriler.jsonl`
- Toplam kaynak referans havuzu: `400087`
- Calisma orneklemi: `10000`
- Ornekleme tipi: random
- Seed: `20260804`

Ilk DOI durumu:

- DOI olan referans: `1948` (`19.48%`)
- DOI olmayan referans: `8052` (`80.52%`)
- Benzersiz DOI: `1931`

## Ana Sonuclar

Ilk DOI-only Crossref kontrolu:

- Crossref'te DOI ile bulunan: `1855`
- Crossref'te DOI ile bulunamayan: `93`
- DOI olanlar icinde Crossref bulunma orani: `95.23%`
- Tum 10000 referans icinde DOI-only bulunma orani: `18.55%`

Crossref bibliyografik fallback sonrasi:

- Strict Crossref eslesme: `5607` (`56.07%`)
- Broad Crossref eslesme: `5826` (`58.26%`)
- DOI'siz referanslarda strong recovery: `3692`
- DOI'siz referanslarda broad recovery: `3908` (`3692 strong + 216 possible`)

Deney 23 sonrasi otomatik cozulmus toplam:

- Bulunan toplam: `7018 / 10000`
- Bulunma orani: `70.18%`
- Kalan: `2987 / 10000`
- Kalan oran: `29.87%`
- Deney 20 (Fuzzy Matching) ile eklenen: `+5`
- Deney 21 (YÖK Tez Resolver) ile eklenen: `+133`
- Deney 22 (Kitap / Book Resolver) ile eklenen: `+153`
- Deney 23 (URL & Web Resolver) ile eklenen: `+317` (589 web kaynağından 317 canlı/arşivlenmiş strong)

Google Scholar / Selenium snapshot:

- SQLite toplam satir: `703`
- `browser` provider satiri: `60`
- `selenium` provider satiri: `643`
- Selenium `unique_result`: `242`
- Selenium `ambiguous`: `211`
- Selenium `no_result`: `72`
- Selenium `unique_no_link`: `118`

## Deney Kronolojisi

### Deney 1 - DOI-only Crossref

Referans metninde DOI bulunan satirlarda DOI normalize edildi ve Crossref
`works/{doi}` endpoint'i ile sorgulandi.

Sonuc:

- `1948` DOI'li referans
- `1855` Crossref DOI eslesmesi
- `93` DOI Crossref'te bulunamadi

Ana dosyalar:

- `root_scripts/trdizin_crossref_doi_stats.py`
- `trdizin_crossref_doi_stats_10k/summary.json`
- `trdizin_crossref_doi_stats_10k/crossref_doi_cache.json`

### Deney 2 - Strict Crossref Bibliyografik Arama

DOI'si olmayan veya DOI ile bulunamayan referanslar icin baslik/yazar/yil gibi
alanlardan Crossref bibliyografik arama yapildi. Strict kural daha yuksek
guvenli eslesmeleri saydi.

Sonuc:

- Strict Crossref eslesme: `5607`
- Strict oran: `56.07%`

Ana dosyalar:

- `root_scripts/trdizin_crossref_bibliographic_fallback.py`
- `trdizin_crossref_doi_stats_10k/combined_crossref_matching_summary.json`
- `trdizin_crossref_doi_stats_10k/crossref_bibliographic_fallback_cache.json`

### Deney 3 - Broad Crossref / Possible Dahil

Strict eslesmelere ek olarak possible/broad eslesmeler de ayri sayildi.

Sonuc:

- Broad Crossref eslesme: `5826`
- Broad oran: `58.26%`
- Strict'e gore ek broad-only: `219`

Ana dosyalar:

- `trdizin_crossref_doi_stats_10k/combined_crossref_matching_report_tr.md`
- `trdizin_crossref_doi_stats_10k/combined_crossref_matching_summary.json`

### Crossref SimpleTextQuery Deneyi

Crossref'in SimpleTextQuery mantigina yakin olacak sekilde referans metniyle
toplu arama yapildi ve mevcut pipeline ile karsilastirildi.

Sonuc:

- SimpleTextQuery bulunan: `5673`
- Oran: `56.73%`
- Kaynak DOI olanlarda STQ bulma orani: `97.48%`
- Kaynak DOI olmayanlarda STQ bulma orani: `46.87%`
- STQ ile pipeline strict kesisimi: `5333`
- STQ-only vs pipeline strict: `340`
- Pipeline strict-only vs STQ: `274`
- DOI mismatch sayisi: `95`

Ana dosyalar:

- `root_scripts/trdizin_simple_text_query_stats.py`
- `trdizin_crossref_doi_stats_10k/simple_text_query_combined/`

### Deney 4 - OpenAlex Ilk Deneme

Crossref'te cikmayan referanslar icin OpenAlex API ile arama yapildi. Bu
asamada rate limit goruldu.

Ana dosyalar:

- `root_scripts/trdizin_openalex_fallback.py`
- `trdizin_crossref_doi_stats_10k/openalex_fallback/`

### Deney 5 - DataCite REST API

DataCite REST API denendi. Sonuclar bundle'da tutuldu, fakat daha sonra
pipeline bu sonucun uzerine kurulmadan devam ettirildi.

Sonuc:

- DataCite hedef toplam: `3929`
- DataCite checked: `3929`
- Strong match: `0`
- Final orana katkisi: `0`

Ana dosyalar:

- `root_scripts/trdizin_datacite_fallback.py`
- `trdizin_crossref_doi_stats_10k/datacite_fallback/`
- `trdizin_crossref_doi_stats_10k/datacite_fallback_smoke/`
- `trdizin_crossref_doi_stats_10k/datacite_fallback_smoke3/`

### Deney 6 - OpenAlex API Key ile Resume

OpenAlex tarafinda daha once rate limit nedeniyle bakilamayan satirlar API key
ile tekrar calistirildi. DataCite pipeline'dan cikarildi; Deney 5 sonucu
dosyalarda tutuldu ama Deney 6 bundan devam etmedi.

Sonuc:

- OpenAlex hedef toplam: `3948`
- OpenAlex checked: `1041`
- Strong match: `20`
- No match: `1021`
- Not checked: `2907`
- Deney 4 partial uzerine ek: `1`
- Not: summary `complete: False`, cunku tum hedef set bitmedi.

Ana dosyalar:

- `trdizin_crossref_doi_stats_10k/openalex_api_key_fallback/`

### Deney 7 - DergiPark OAI-PMH Direct Filter

Referanstaki DergiPark article id / kayit bilgileriyle OAI-PMH `GetRecord` veya
`ListRecords` mantiginda sorgu yapildi. Bu deney sadece OAI ile sorgulanabilir
olan hedeflerde etkili oldu.

Sonuc:

- DergiPark target total: `3928`
- OAI queryable: `27`
- Strong match: `27`
- Deney 7 sonrasi bulunan: `6099`
- Oran: `60.99%`

Ana dosyalar:

- `root_scripts/trdizin_dergipark_oai_fallback.py`
- `trdizin_crossref_doi_stats_10k/dergipark_oai_fallback/`

### Deney 8 - Crossref Cleanup + Query Variants

Kalan article-like referanslarda query temizleme ve alternatif sorgu varyantlari
denendi.

Sonuc:

- Queryable hedef: `849`
- Strong match: `2`
- Deney 8 sonrasi bulunan: `6101`
- Oran: `61.01%`

Ana dosyalar:

- `root_scripts/trdizin_crossref_cleanup_fallback.py`
- `trdizin_crossref_doi_stats_10k/crossref_cleanup_fallback/`

### Deney 9 - Europe PMC Biomedical Fallback

Biomedical referanslar icin Europe PMC sorgulandi.

Sonuc:

- Target total: `81`
- Strong match: `22`
- DOI'li Europe PMC match: `3`
- Deney 9 sonrasi bulunan: `6123`
- Oran: `61.23%`

Ana dosyalar:

- `trdizin_crossref_doi_stats_10k/europepmc_fallback/`

### Deney 10 - DergiPark Article-file Probe

DergiPark article-file linklerinden ek match cikarmak denendi. Bu asamada yeni
strong match gelmedi, fakat kalan referanslar kategorilere ayrildi.

Sonuc:

- Article-file target: `15`
- Strong match: `0`
- Deney 10 sonrasi bulunan: `6123`
- Kalan: `3877`

Ana dosyalar:

- `root_scripts/trdizin_dergipark_article_file_probe.py`
- `trdizin_crossref_doi_stats_10k/dergipark_article_file_probe/`
- `trdizin_crossref_doi_stats_10k/remaining_after_experiment10/`

### Deney 11 - Journal-like Parser + DergiPark Local Index

Kalan journal-like referanslar daha iyi parse edildi; DergiPark local index
ile eslestirme denendi.

Sonuc:

- Journal-like hedef: `740`
- DergiPark indexed records: `1697`
- Strong match: `1`
- Deney 11 sonrasi bulunan: `6124`

Ana dosyalar:

- `root_scripts/trdizin_experiment11_journal_like_parser_dergipark.py`
- `trdizin_crossref_doi_stats_10k/experiment11_journal_like/`

### Deney 12 - TR Dizin TargetPublication Resolver

Referansin hedef yayin bilgisi TR Dizin metadata ile eslestirildi. Crossref DOI
dogrulanmis ve TR Dizin id-only/unverified DOI eslesmeleri ayri sayildi.

Sonuc:

- TargetPublication toplam: `749`
- Base sonrasi aday: `239`
- Strong match: `239`
- Crossref DOI dogrulu bulunan: `13`
- ID-only veya unverified DOI: `226`
- Deney 12 sonrasi bulunan: `6363`
- Oran: `63.63%`

Ana dosyalar:

- `root_scripts/trdizin_experiment12_trdizin_target_publication.py`
- `trdizin_crossref_doi_stats_10k/experiment12_trdizin_target/`

### Deney 13 - TR Dizin Title Search Resolver

Kalan basliklardan TR Dizin title search ile eslestirme denendi.

Sonuc:

- Title search hedef: `551`
- Strong match: `4`
- Deney 13 sonrasi bulunan: `6367`
- Oran: `63.67%`

Ana dosyalar:

- `root_scripts/trdizin_experiment13_trdizin_title_search.py`
- `trdizin_crossref_doi_stats_10k/experiment13_trdizin_title_search/`

### Deney 14 - Hidden DOI Cleanup

Metnin icinde gizli/normal formda olmayan DOI adaylari arandi.

Sonuc:

- Hidden DOI target: `11`
- Strong match: `0`
- Oran degismedi: `63.67%`

Ana dosyalar:

- `root_scripts/trdizin_experiments14_18_resolvers.py`
- `trdizin_crossref_doi_stats_10k/experiment14_hidden_doi/`

### Deney 15 - DergiPark Article-file Resolver

DergiPark article-file kalanlari icin ek resolver denendi.

Sonuc:

- Target: `11`
- Strong match: `0`
- Oran degismedi: `63.67%`

Ana dosyalar:

- `trdizin_crossref_doi_stats_10k/experiment15_dergipark_article_file/`

### Deney 16 - ISBN / Book Resolver

Kitap / kitap bolumu referanslari icin ISBN ve kitap odakli resolver denendi.

Sonuc:

- ISBN target: `9`
- Unique ISBN candidate: `11`
- Strong match: `0`
- Oran degismedi: `63.67%`

Ana dosyalar:

- `trdizin_crossref_doi_stats_10k/experiment16_isbn_book/`

### Deney 17 - DOI Eligible Denominator

Bu deney yeni match eklemedi; kalan referanslar icinde DOI beklenmesi zayif
olan turler ayri denominator disina alindi.

Sonuc:

- Otomatik cozulmus: `6367`
- Kalan: `3633`
- DOI-unlikely kalan: `1962`
- Operasyonel DOI-eligible denominator: `8038`
- Bu denominator uzerinden cozum orani: `79.21%`

Ana dosyalar:

- `trdizin_crossref_doi_stats_10k/experiment17_doi_eligible_denominator/`

### Deney 18 - PubMed Citation Matcher

PubMed ecitmatch / metadata sorgulari ile biomedical referanslarda ek cozum
arandi.

Sonuc:

- PubMed target: `50`
- PMID bulunan: `15`
- Possible match: `15`
- Strong DOI match: `0`
- Oran degismedi: `63.67%`

Ana dosyalar:

- `trdizin_crossref_doi_stats_10k/experiment18_pubmed_citation_matcher/`

### Deney 19 - GROBID Re-parse + Resolver Retry

Kalan referanslar GROBID ile yeniden parse edildi; GROBID title/year/DOI
alanlari kullanilarak Crossref, OpenAlex ve TR Dizin title search tekrar
denendi.

Sonuc:

- Deney 19 oncesi bulunan: `6367`
- GROBID retry target: `1302`
- GROBID alignment bulunan kalan: `3445`
- GROBID title bulunan: `3158`
- GROBID title+year bulunan: `3058`
- GROBID DOI bulunan: `42`
- Strong match: `43`
- Deney 19 sonrasi bulunan: `6410`
- Oran: `64.10%`
- Kalan: `3590`

Ana dosyalar:

- `root_scripts/trdizin_experiment19_grobid_reparse_retry.py`
- `trdizin_crossref_doi_stats_10k/experiment19_grobid_reparse/`
- `trdizin_crossref_doi_stats_10k/remaining_after_experiment19/`

### Deney 20 - Fuzzy Matching & Esnek Arama

Kalan 3.590 referans üzerinde harf hatalarını, Türkçe karakter farklarını ve format bozukluklarını tolere eden Gestalt + Damerau-Levenshtein + Jaro-Winkler hibrit benzerlik modeli uygulandı.

Sonuc:

- Processed: `3590`
- New Strong Match: `5`
- Toplam bulunan: `6415`
- Oran: `64.15%`

Ana dosyalar:

- `root_scripts/trdizin_experiment20_fuzzy_matching.py`
- `trdizin_crossref_doi_stats_10k/experiment20_fuzzy/`

### Deney 21 - YÖK Ulusal Tez Merkezi Resolver

Kalan referans havuzundaki 291 lisansüstü tez (Yüksek Lisans, Doktora, Uzmanlık), YÖK Ulusal Tez Merkezi (`tez.yok.gov.tr`) arama motoru ve künye doğrulayıcısı üzerinden sorgulandı. Tez No, yazar, başlık ve üniversite mutabakatı ile kesin kayıtlar eşleştirildi.

Sonuc:

- Hedef Tez Sayısı: `291`
- Strong Match: `133` (%45.70 tez çözüm oranı)
- Possible Match: `12`
- Eşleşmeyen: `146` (önemli bir kısmı yurt dışı tezler - Westminster, Rice, Bangladesh vb.)
- Deney 21 sonrası toplam bulunan: `6548 / 10000`
- Toplam oran: `65.48%`
- Kalan toplam: `3452 / 10000` (%34.52)
- Kalan tez kategorisi: `158` (%4.58)

Ana dosyalar:

- `root_scripts/trdizin_experiment21_yok_tez_resolver.py`
- `trdizin_crossref_doi_stats_10k/experiment21_yok_tez/yok_tez_matches.jsonl`
- `trdizin_crossref_doi_stats_10k/experiment21_yok_tez/yok_tez_matches.csv`
- `trdizin_crossref_doi_stats_10k/experiment21_yok_tez/yok_tez_summary.json`
- `trdizin_crossref_doi_stats_10k/experiment21_yok_tez/yok_tez_report_tr.md`
- `trdizin_crossref_doi_stats_10k/remaining_after_experiment21/`

### Deney 22 - Kitap ve Kitap Bölümü Resolver

Kalan havuzdaki 949 basılı ve elektronik kitap / kitap bölümü referansı; OpenLibrary API, Toplu Katalog (TO-KAT / Milli Kütüphane) ve Crossref Books motorları üzerinden taranarak ISBN, OpenLibrary Works Key ve Book DOI atamaları ile eşleştirildi.

Sonuc:

- Hedef Kitap Sayısı: `949`
- Strong Match: `153` (%16.12 kitap havuzu çözüm oranı)
- Possible Match: `19`
- Eşleşmeyen: `777` (yerel küçük yayınevleri, kurum içi özel basımlar veya çok eski baskılar)
- Deney 22 sonrası toplam bulunan: `6701 / 10000`
- Toplam oran: `67.01%`
- Kalan toplam: `3299 / 10000` (%32.99)
- Kalan kitap kategorisi: `796` (%24.13)

Ana dosyalar:

- `root_scripts/trdizin_experiment22_book_resolver.py`
- `trdizin_crossref_doi_stats_10k/experiment22_books/book_matches.jsonl`
- `trdizin_crossref_doi_stats_10k/experiment22_books/book_matches.csv`
- `trdizin_crossref_doi_stats_10k/experiment22_books/book_summary.json`
- `trdizin_crossref_doi_stats_10k/experiment22_books/book_report_tr.md`
- `trdizin_crossref_doi_stats_10k/remaining_after_experiment22/`

### Deney 23 - URL & Web / Wayback Machine Resolver

Kalan havuzdaki 589 web kaynağı, online veri seti, haber, video ve resmi kurum raporu; URL normalizasyonu, canlı HTTP 200/301/302 doğrulama ve Internet Archive Wayback Machine kurtarma motoru üzerinden sorgulandı.

Sonuc:

- Hedef Web / URL Referansı: `589`
- Strong Match: `317` (%53.82 web havuzu çözüm oranı)
  - Canlı Aktif URL (HTTP 200): `317`
  - Wayback Machine Kurtarma: `0`
- Eşleşmeyen / Kırık / URL içermeyen: `272`
- Deney 23 sonrası toplam bulunan: `7018 / 10000`
- Toplam oran: `70.18%` (%70 barajı aşıldı)
- Kalan toplam: `2987 / 10000` (%29.87)
- Kalan web kategorisi: `220` (%7.37)

Ana dosyalar:

- `root_scripts/trdizin_experiment23_url_web_resolver.py`
- `trdizin_crossref_doi_stats_10k/experiment23_url_web/url_matches.jsonl`
- `trdizin_crossref_doi_stats_10k/experiment23_url_web/url_matches.csv`
- `trdizin_crossref_doi_stats_10k/experiment23_url_web/url_summary.json`
- `trdizin_crossref_doi_stats_10k/experiment23_url_web/url_report_tr.md`
- `trdizin_crossref_doi_stats_10k/remaining_after_experiment23/`

## Deney 23 Sonrasi Kalan Referans Kategorileri

Deney 23 sonrasi kalan `2987` referansin exclusive kategori dagilimi:

| Kategori | Etiket | Count | Kalan icindeki oran |
|---|---:|---:|---:|
| `other` | Diger / zayif parse | `1071` | `35.86%` |
| `book_or_chapter` | Kitap / kitap bolumu | `796` | `26.65%` |
| `journal_like_left` | Journal-like kalan | `551` | `18.45%` |
| `url_web` | Web / haber / video | `220` | `7.37%` |
| `thesis` | Tez | `150` | `5.02%` |
| `report_policy_legal` | Rapor / mevzuat / hukuk | `136` | `4.55%` |
| `conference` | Konferans / bildiri | `52` | `1.74%` |
| `hidden_doi` | Gizli DOI | `11` | `0.37%` |

Dashboard'a bu kategori dagilimi ve kategori ornekleri icin "ornek goster"
akisi eklendi.

Ana dosyalar:

- `crossref_stats_dashboard/index.html`
- `crossref_stats_dashboard/app.js`
- `crossref_stats_dashboard/styles.css`

## Google Scholar / Selenium Calismasi

Crossref ve diger resolver'larda cikmayan referanslar icin Google Scholar
uzerinden kaynak linki bulma denendi.

Kural:

- Scholar sonuc sayisi tam `1` ve bu tek sonucun linki varsa `selected_link`
  kaydedilir.
- Sonuc `0` ise `selected_link = NULL`.
- Sonuc `2+` ise ambiguous kabul edilir ve `selected_link = NULL`.
- Tek sonuc var ama tiklanabilir link yoksa `unique_no_link` yazilir ve
  `selected_link = NULL`.

Once SerpAPI uyumlu collector yazildi:

- `root_scripts/trdizin_google_scholar_link_collector.py`

Sonra lokal tarayici ile Playwright tabanli collector yazildi:

- `root_scripts/trdizin_google_scholar_browser_collector.py`

Daha sonra kullanici istegiyle Selenium collector yazildi:

- `root_scripts/trdizin_google_scholar_selenium_collector.py`

Selenium icin eklenen korumalar:

- Chrome profile ayrimi
- `page_load_strategy = eager`
- `--page-load-timeout`
- `--captcha-mode wait`
- `--stop-on-captcha`
- CAPTCHA bypass edilmedi; manuel cozum bekleme veya durma davranisi kullanildi.

SQLite dosyasi:

```text
trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links.sqlite
```

SQLite tablo ozeti:

| Provider | Status | Count |
|---|---:|---:|
| `browser` | `ambiguous` | `25` |
| `browser` | `no_result` | `5` |
| `browser` | `unique_no_link` | `10` |
| `browser` | `unique_result` | `20` |
| `selenium` | `ambiguous` | `211` |
| `selenium` | `no_result` | `72` |
| `selenium` | `unique_no_link` | `118` |
| `selenium` | `unique_result` | `242` |

Not: Selenium full run Google Scholar robot dogrulamasina takildi. Bundle
snapshot'inda o ana kadar DB'ye yazilan `643` Selenium satiri vardir.

## SQLite / Datasette

DB terminalde acmak icin:

```bash
sqlite3 trdizin_reference_matching_bundle_2026-08-07/trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links.sqlite
```

Ornek sorgular:

```sql
.tables
.schema scholar_reference_links
select provider, status, count(*)
from scholar_reference_links
group by provider, status
order by provider, status;

select sample_index, publication_id, reference_id, status, selected_title, selected_link
from scholar_reference_links
where provider = 'selenium' and selected_link is not null
limit 20;
```

Datasette ile acmak icin:

```bash
python3 -m datasette serve trdizin_reference_matching_bundle_2026-08-07/trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links.sqlite --host 127.0.0.1 --port 8011 --setting default_allow_sql on
```

## Bundle Icerigi

Bu bundle su ana kisimlardan olusur:

- `root_inputs/`: `veriler.jsonl`, GROBID metadata JSONL dosyalari ve loglar.
- `root_scripts/`: Calisma boyunca yazilan/kullanilan Python scriptleri.
- `trdizin_crossref_doi_stats_10k/`: Tum deney summary, report, cache, match
  CSV/JSONL dosyalari ve Google Scholar SQLite DB snapshot'i.
- `crossref_stats_dashboard/`: Deney sonuclarini gosteren lokal dashboard.
- `github_dashboard/`: Onceki dashboard/progress artefaktlari.
- `FILE_MANIFEST.txt`: Bundle icindeki tum dosyalarin listesi.
- `BUNDLE_README.md`: Bundle yapisinin kisa aciklamasi.

Bundle son kontrolu:

- Dosya sayisi: `228`
- Yaklasik boyut: `600M`
- Google Scholar DB integrity: `ok`

## Haric Tutulanlar

Asagidaki klasorler bilerek bundle'a alinmadi:

- `trdizin_pdfler/`: yaklasik `1.0 GB`, ham PDF arsivi.
- `grobid_references_tei/`: yaklasik `422 MB`, ham GROBID TEI ciktilari.
- Google Chrome / Selenium profil klasorleri:
  - `google_scholar_links/browser_profile/`
  - `google_scholar_links/selenium_profile/`
  - `google_scholar_links/selenium_profile_wait/`
  - `google_scholar_links/selenium_profile_eager/`

Sebep: PDF/TEI klasorleri cok buyuk ham kaynak arsivi; browser profil
klasorleri ise lokal session/cookie/cache verisi icerebilir.

## Tekrar Uretim Notlari

Python paketlerini kurmak icin:

```bash
python3 -m pip install -r trdizin_reference_matching_bundle_2026-08-07/requirements.txt
```

Google Scholar collector'lari icin Google Chrome gerekir. Deney 19 GROBID
re-parse akisi icin GROBID servisinin `http://localhost:8072` adresinde ayakta
olmasi gerekir.

Ana 10K Crossref istatistigi:

```bash
python3 root_scripts/trdizin_crossref_doi_stats.py
```

Google Scholar Selenium collector:

```bash
python3 root_scripts/trdizin_google_scholar_selenium_collector.py \
  --input trdizin_crossref_doi_stats_10k/remaining_after_experiment19/remaining_after_experiment19_references.jsonl \
  --db trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links.sqlite \
  --pause-ms 7000 \
  --wait-ms 2200 \
  --page-load-timeout 25 \
  --commit-every 5 \
  --captcha-mode wait \
  --captcha-timeout 1200 \
  --stop-on-captcha
```

Google Scholar uzerinde otomatik CAPTCHA bypass yapilmadi ve yapilmamali.
Robot dogrulamasi cikarsa manuel cozum gerekir; aksi halde run durdurulmalidir.

## Son Yorum

En buyuk artis Crossref bibliyografik fallback ve TR Dizin targetPublication
resolver'dan geldi. OpenAlex, DergiPark OAI ve GROBID re-parse daha kucuk ama
gercek ek kazanimlar sagladi. DataCite, hidden DOI, ISBN, article-file ve
PubMed adimlari bu orneklemde anlamli yeni DOI eslesmesi uretmedi. Kalan
referanslarin buyuk bolumu kitap/bolum, zayif parse, web, tez, rapor ve benzeri
DOI beklenmesi zayif veya bibliyografik olarak eksik turlerde yogunlasti.
