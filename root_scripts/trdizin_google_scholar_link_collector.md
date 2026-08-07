# Google Scholar Link Collector

Bu script referans satirlarini Google Scholar uzerinde arar ve sonucu SQLite DB'ye yazar.
Dogru kullanim icin SerpAPI Google Scholar engine kullanilir; direkt Scholar HTML scraping
captcha ve blok riski nedeniyle script'e konulmadi.

## Kural

- Arama sonucu tam `1` adet gelirse `selected_link` dolu kaydedilir.
- Arama sonucu `0` veya `2+` adet gelirse `selected_link` `NULL` kaydedilir.
- Arama sonucu tam `1` adet olup tıklanabilir link yoksa status `unique_no_link`
  olur ve `selected_link` yine `NULL` kalir.
- Referans metni, kategori ve TR Dizin id alanlari ayni satirda tutulur.

## Calistirma

```bash
export SERPAPI_KEY="..."
python3 trdizin_google_scholar_link_collector.py \
  --input trdizin_crossref_doi_stats_10k/remaining_after_experiment19/remaining_after_experiment19_references.jsonl \
  --db trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links.sqlite \
  --category journal_like_left \
  --sleep 2
```

Birden fazla kategori:

```bash
python3 trdizin_google_scholar_link_collector.py \
  --category journal_like_left \
  --category other \
  --limit 100
```

Tekil ornek:

```bash
python3 trdizin_google_scholar_link_collector.py \
  --sample-index 1197
```

DB kontrolu:

```bash
sqlite3 trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links.sqlite \
  "select sample_index, status, result_count, selected_link from scholar_reference_links limit 10;"
```

Test modu:

```bash
python3 trdizin_google_scholar_link_collector.py \
  --provider mock \
  --limit 5 \
  --overwrite
```

## Tarayici Modu

SerpAPI kullanmadan, lokal Chrome/Chromium penceresiyle aramak icin:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium

python3 trdizin_google_scholar_browser_collector.py \
  --category journal_like_left \
  --limit 50 \
  --pause-ms 9000
```

Bu mod Google Scholar HTML'ini tarayicida acar ve sonucu ayni SQLite tablosuna
`provider = browser` olarak yazar. Tam `1` organik sonuc varsa link kaydedilir;
`0`, `2+`, ya da linksiz tek sonuc varsa `selected_link` `NULL` kalir.

CAPTCHA veya blok sayfasi gelirse varsayilan davranis satiri `captcha` status'u
ile kaydetmektir. Manuel cozmek icin:

```bash
python3 trdizin_google_scholar_browser_collector.py \
  --captcha-mode wait \
  --captcha-timeout 180 \
  --limit 20
```

## Selenium Modu

Playwright yerine Selenium ile lokal Chrome kullanmak icin:

```bash
python3 -m pip install selenium

python3 trdizin_google_scholar_selenium_collector.py \
  --pause-ms 7000 \
  --wait-ms 2200 \
  --page-load-timeout 25 \
  --stop-on-captcha
```

Bu mod ayni SQLite tablosuna `provider = selenium` olarak yazar. CAPTCHA veya
blok sayfasi gelirse varsayilan olarak satiri `captcha` status'u ile kaydeder;
CAPTCHA bypass etmez. `--stop-on-captcha` full kosuda kalan satirlari yanlis
`captcha` ile doldurmamak icin ilk CAPTCHA'da durdurur.
