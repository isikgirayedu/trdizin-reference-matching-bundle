# Kurulum Kontrolu

```bash
pip install --dry-run -r requirements.txt
```

# Kullanilan Dosyalar Bundle

Bu klasor, ilk mesajdan beri TR Dizin / Crossref / OpenAlex / DergiPark /
Google Scholar eslestirme isi icin kullandigimiz ana dosyalarin kopyasidir.
Orijinal dosyalar tasinmadi; bu klasor sadece kopya/snapshot amaclidir.

## Icerik

- `root_scripts/`: Calistirdigimiz veya bu is icin yazdigimiz Python scriptleri
  ve ilgili README/dokuman dosyalari.
- `root_inputs/`: Ilk TR Dizin/GROBID veri kaynaklari ve dashboard loglari
  (`veriler.jsonl`, GROBID metadata JSONL dosyalari, hata loglari).
- `trdizin_crossref_doi_stats_10k/`: Deney ciktisi, cache, match CSV/JSONL,
  summary/report dosyalari ve Google Scholar SQLite DB snapshot'i.
- `crossref_stats_dashboard/`: Deney istatistiklerini gosteren lokal dashboard.
- `github_dashboard/`: Onceki ilerleme/dashboard artefaktlari.
- `FILE_MANIFEST.txt`: Bu bundle icindeki dosyalarin tam listesi.
- `CALISMA_RAPORU.md`: Ilk mesajdan itibaren yapilan deneyleri, sonuclari,
  Google Scholar/Selenium adimini ve tekrar calistirma notlarini anlatan ana
  rapor.
- `requirements.txt`: Python paketleri, runtime notlari ve gerekli sistem
  servisleri.

## Google Scholar DB

SQLite dosyasi:

```bash
trdizin_reference_matching_bundle_2026-08-07/trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links.sqlite
```

Terminalde acmak icin:

```bash
sqlite3 trdizin_reference_matching_bundle_2026-08-07/trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links.sqlite
```

Datasette ile webden acmak icin:

```bash
python3 -m datasette serve trdizin_reference_matching_bundle_2026-08-07/trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links.sqlite --host 127.0.0.1 --port 8011 --setting default_allow_sql on
```

## Haric Tutulanlar

Asagidaki Chrome/Selenium profil klasorleri kasten kopyalanmadi, cunku lokal
browser session/cookie/cache verisi icerebilirler ve analiz sonucunu yeniden
uretmeye gerek yoktur:

- `trdizin_crossref_doi_stats_10k/google_scholar_links/browser_profile/`
- `trdizin_crossref_doi_stats_10k/google_scholar_links/selenium_profile/`
- `trdizin_crossref_doi_stats_10k/google_scholar_links/selenium_profile_wait/`
- `trdizin_crossref_doi_stats_10k/google_scholar_links/selenium_profile_eager/`

SQLite `-wal` ve `-shm` gecici dosyalari da kopyalanmadi; DB snapshot'i
`sqlite3 .backup` ile tek `.sqlite` dosyasi olarak alindi.

Buyuk ham kaynak klasorleri de kopyalanmadi:

- `trdizin_pdfler/` yaklasik 1.0 GB
- `grobid_references_tei/` yaklasik 422 MB

Bu bundle analiz ciktisi, cache, match ve DB tarafini toplar. Ham PDF/TEI
arsivi gerektiginde orijinal workspace path'lerinden kullanilmalidir.
