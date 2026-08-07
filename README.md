# Kurulum Kontrolu

```bash
pip install --dry-run -r requirements.txt
```

# TR Dizin Reference Matching Bundle

Bu repo, TR Dizin referans DOI / kaynak eslestirme calismasinda kullanilan
scriptleri, deney ciktilarini, raporlari, dashboard dosyalarini ve Google
Scholar SQLite snapshot'ini icerir.

Ana dosyalar:

- `CALISMA_RAPORU.md`: Yapilan tum deneylerin ve sonuclarin ana raporu.
- `BUNDLE_README.md`: Bundle klasor yapisi, DB acma notlari ve haric tutulan
  ham kaynaklar.
- `requirements.txt`: Python paketleri ve sistem gereksinimi notlari.
- `FILE_MANIFEST.txt`: Repodaki dosyalarin tam listesi.
- `trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links.sqlite`:
  Google Scholar browser/Selenium sonuclarinin SQLite snapshot'i.

Detayli calisma ozeti icin once `CALISMA_RAPORU.md` okunmalidir.
