# TR Dizin Ground Truth ile GROBID Citation Training Raporu

Rapor tarihi: 2026-07-20  
Proje klasoru: `/Users/isikgiray/Desktop/ULAKBİM/grobid`

## 1. Ozet

Bu calismanin amaci, GROBID'in `citation` modelini Turkce/TR Dizin agirlikli
referanslar icin iyilestirecek training corpus uretmektir. Normal GROBID
training akisi insan tarafindan duzeltilmis TEI XML ister. Bu projede manuel
duzeltme yerine TR Dizin API'sindeki kaynakca metinleri ground truth kabul
edildi ve GROBID'in mevcut modelle cikardigi referans TEI dosyalari otomatik
olarak TR Dizin referans metinlerine hizalandi.

Ana fikir sudur:

```text
TR Dizin yayin id'leri
  -> TR Dizin metadata/referanslari
  -> PDF ve GROBID processReferences TEI ciktisi
  -> TR Dizin raw referansi ile GROBID raw referansini eslestirme
  -> GROBID'in alan etiketlerini TR Dizin metnine projekte etme
  -> citation training corpus
  -> TRUBA uzerinde Wapiti/DeLFT training denemeleri
```

Bu yontem tum GROBID'i bastan egitmez. Hedeflenen parca `citation` modelidir:
tek bir bibliyografik referans string'ini `author`, `title`, `date`, `journal`,
`volume`, `issue`, `pages`, `DOI` gibi alanlara ayiran model.

## 2. Problem Tanimi

GROBID bilimsel PDF'leri TEI XML'e donustururken cascade bir model mimarisi
kullanir. Kaynakca tarafinda iki farkli model onemlidir:

- `reference-segmenter`: PDF'teki kaynakca bolumunu tek tek referans kayitlarina
  ayirir.
- `citation`: tek bir referans kaydi icindeki alanlari etiketler.

Bu projede odak `citation` modelidir. TR Dizin'de yayin metadata'si icinde
referanslarin raw metinleri bulundugu icin, bu metinler citation modeli icin
ground truth raw referans olarak kullanildi. Ancak TR Dizin referansi sadece raw
metindir; alan etiketleri yoktur. Alan etiketleri icin GROBID'in mevcut model
ciktisindan yararlanildi.

Bu nedenle veri uretim problemi iki parcaya ayrildi:

1. TR Dizin referansini, ayni referansin GROBID tarafindan bulunan raw metniyle
   eslestirmek.
2. GROBID'in mevcut TEI alan etiketlerini TR Dizin raw metni uzerine mumkun
   oldugunca guvenli sekilde projekte etmek.

## 3. Kullanilan Yerel Artifact'ler

| Artifact | Rol |
| --- | --- |
| `sadece_idler.txt` | Islenecek TR Dizin yayin id listesi. Yerelde 10,000 id var. |
| `download_pdfs.py` | Id listesinden PDF indirmek icin yardimci script. |
| `trdizin_100_pdf.py` | TR Dizin arama API'sinden acik erisim PDF toplamak icin alternatif indirici. |
| `trdizin_viewer_service.py` | TR Dizin metadata/PDF cekme fonksiyonlarinin ortak kullanildigi servis modulu. |
| `generate_trdizin_reference_training.py` | Ilk asama: TR Dizin referanslari, GROBID `createTraining` ZIP'leri ve eslesme raporlari uretir. |
| `extract_grobid_references.py` | PDF'lerden GROBID `processReferences` TEI ciktisi uretme hattinda kullanildi. |
| `grobid_references_tei/` | GROBID'in mevcut modelle cikardigi referans TEI dosyalari. |
| `build_trdizin_corrected_reference_corpus.py` | Ana corpus uretici: TR Dizin referanslarini ground truth raw metin kabul edip corrected TEI ve citation corpus uretir. |
| `trdizin_corrected_reference_corpus/` | Uretilen corrected TEI, citation corpus, manifest, match report ve review queue klasoru. |
| `TrainWapitiFromFeatures.java` | Precomputed `.train` feature dosyasindan Wapiti training baslatmak icin yardimci Java wrapper. |
| `train_citation_from_features.sbatch` | Feature generation beklemeden staged Wapiti training baslatan Slurm scripti. |
| `train_citation_full_delft_gpu.sbatch` | Ayri full DeLFT citation GPU denemesi icin Slurm scripti. |
| `github_dashboard/` | GitHub Pages uzerinden training durumunu yayinlayan statik dashboard dosyalari. |

## 4. Veri Durumu

Yerel dosya sayimlarina gore mevcut durum:

| Veri | Sayim |
| --- | ---: |
| `sadece_idler.txt` | 10,000 yayin id |
| `grobid_tei_xml/` | 9,997 TEI XML |
| `grobid_tei_xml_ch2/` | 9,997 TEI XML |
| `grobid_references_tei/` | 9,879 `processReferences` TEI XML |
| `trdizin_corrected_reference_corpus/corrected_references_tei/` | 9,833 corrected TEI XML |
| `trdizin_corrected_reference_corpus/citation_corpus/` | 9,689 citation corpus XML |
| `trdizin_corrected_reference_corpus/manifest.jsonl` | 10,121 isleme kaydi |
| `trdizin_corrected_reference_corpus/match_report.jsonl` | 9,833 dokuman raporu |
| `trdizin_corrected_reference_corpus/review_queue.csv` | 91,922 review satiri |
| `trdizin_corrected_reference_corpus/errors.txt` | 121 hata satiri |

Manifest append-only tutuldugu icin satir sayisi yayin id sayisindan fazla
olabilir. Bu durum tekrar denemeler, atlanan kayitlar veya onceki run'lardan
kalan kayitlarla uyumludur.

## 5. Ground Truth Uretim Akisi

### 5.1 Id ve PDF Katmani

Baslangic noktasi `sadece_idler.txt` dosyasindaki TR Dizin yayin id'leridir.
PDF gerekiyorsa `download_pdfs.py` veya `trdizin_100_pdf.py` ile indirildi.
`download_pdfs.py`, id listesini okur, her id icin TR Dizin'den PDF bytes ceker,
dosyanin gercekten PDF olup olmadigini kontrol eder ve `*.pdf.part` gibi gecici
dosya mantigiyla yarim indirmeleri asil dosyanin uzerine yazmaz.

### 5.2 TR Dizin Metadata

Her yayin icin TR Dizin metadata'si cekildi. Metadata icindeki `references`
listesi ground truth kaynagi olarak kullanildi. Her referans icin onemli alan:

```text
references[].context
```

Bu alan, GROBID'e ogretmek istedigimiz temiz/kurumsal referans metni olarak
kabul edildi. TR Dizin tarafindan verilen `order`, `id`, `authors`, `year`,
`journalCode` ve `targetPublication` gibi ek alanlar raporlama ve izlenebilirlik
icin saklandi; training'in asil raw metni `context` oldu.

### 5.3 GROBID Ilk Cikti

PDF'ler GROBID'e verilerek mevcut modelle referans TEI uretildi. Bu is icin
`processReferences` endpoint'i kullanildi:

```text
POST /api/processReferences
consolidateCitations=0
includeRawCitations=1
```

`includeRawCitations=1` onemliydi, cunku GROBID TEI icinde
`note type="raw_reference"` alanini uretir. Bu raw metin TR Dizin raw metniyle
eslestirme icin kullanildi.

Ilk deneylerde `createTraining` endpoint'i de kullanildi. Bu endpoint GROBID'in
training ZIP uretme yolunu test etmek, reference/citation training dosyalarini
incelemek ve GROBID'in bekledigi dosya formatini dogrulamak icin faydali oldu.

## 6. TR Dizin - GROBID Referans Eslestirme

`build_trdizin_corrected_reference_corpus.py` her yayin icin iki listeyi okur:

- TR Dizin referanslari: metadata `references[].context`
- GROBID referanslari: `grobid_references_tei/<id>.tei.xml` icindeki
  `listBibl` elemanlari ve `note type="raw_reference"`

Eslestirme fuzzy string similarity ile yapildi. Normalizasyon adimlari:

- Referans basindaki `1.`, `[1]`, `1)` gibi numaralandirmalari temizleme.
- Unicode casefold uygulama.
- NFKD normalizasyonu ve diacritic temizleme.
- URL ve `doi:` prefix'lerini etkisizlestirme.
- Harf/rakam disi karakterleri bosluga indirme.
- Bosluklari normalize etme.

Sonra `SequenceMatcher` ratio skoru hesaplandi. Varsayilan esik:

```text
--match-threshold 0.72
```

Her TR Dizin referansi, en iyi GROBID adayiyla eslestirildi. Aday skor esigin
altindaysa training'e alinmadi ve review queue'ye yazildi.

## 7. Alan Etiketlerini TR Dizin Metnine Projeksiyon

TR Dizin referansi raw metindir; alan etiketlerini dogrudan vermez. Bu nedenle
GROBID'in mevcut TEI ciktisindaki alanlar kaynak olarak kullanildi:

- `title level="a"`: makale basligi
- `title level="j"`: dergi basligi
- `title level="m"`: kitap/monografi basligi
- `date`
- `biblScope type/unit`: volume, issue, page
- `idno type="doi"`
- `ptr target`: URL
- `author`: basliktan once kalan yazar bolgesi

Bu alanlar once GROBID TEI'den cikarildi, sonra TR Dizin `context` metni icinde
aranarak span'lere donusturuldu. Arama iki seviyeli calisti:

1. Exact/case-insensitive span arama.
2. Basarisiz olursa normalize edilmis metin uzerinden span bulup orijinal
   karakter index'lerine geri haritalama.

Projeksiyon sonunda her referans icin inline citation training satiri uretildi.
Ornek soyut format:

```xml
<citations>
    <bibl><author>...</author> <title level="a">...</title> ...</bibl>
</citations>
```

## 8. Training'e Alma ve Review Queue

Her eslesen referans otomatik olarak training'e alinmadi. Filtreler:

```text
match_threshold = 0.72
min_labeled_spans = 2
min_labeled_char_ratio = 0.30
```

Bir referans su durumlardan birinde review queue'ye dustu:

- `no_grobid_candidate`: GROBID tarafinda uygun aday yok.
- `low_reference_match`: TR Dizin raw referansi ile GROBID raw referansi yeterince benzemiyor.
- `weak_field_projection`: Referans eslesti ama alan etiketleri TR Dizin metnine guvenli projekte edilemedi.

Bu tasarim bilincli olarak muhafazakar yapildi. Amac, otomatik uretilen corpus'a
cok zayif veya supheli etiketleri sokmamakti. Bu yuzden 9,833 corrected TEI
uretilmesine karsilik citation corpus dosyasi 9,689 dokumanda olustu.

## 9. Uretilen Ciktilar

Ana cikti klasoru:

```text
trdizin_corrected_reference_corpus/
```

Alt ciktilar:

```text
corrected_references_tei/
  TR Dizin raw referanslarini iceren, GROBID alanlari hizalanmis TEI dosyalari.

citation_corpus/
  GROBID citation trainer'in okuyabilecegi *.training.references.tei.xml dosyalari.

manifest.jsonl
  Her yayin icin status, sayim ve cikti path bilgileri.

match_report.jsonl
  Her yayin icin referans bazli eslesme skorlari, dahil/review kararlari ve nedenler.

review_queue.csv
  Otomatik training'e alinmayan referanslarin manuel inceleme listesi.

errors.txt
  Metadata, TEI veya isleme hatasi alan id'ler.
```

Corpus GROBID tarafina su klasore kopyalanarak training'e hazirlandi:

```text
grobid-trainer/resources/dataset/citation/corpus
```

## 10. TRUBA Training Denemeleri

### 10.1 Normal Wapiti Training

Ilk yaklasim GROBID'in standart `train_citation` gorevini TRUBA'da calistirmakti.
Bu yol TEI corpus'tan once feature dosyasini uretir, sonra Wapiti CRF training'e
girer.

Onemli tespitler:

- Java 21 gerekliydi; Mac tarafinda Java 21 bulunmadigi icin TRUBA tercih edildi.
- Ilk memory denemeleri yetersiz kaldi; Wapiti feature matrisi cok buyuk.
- Training ozeti su seviyedeydi:

```text
nb train:    315568
nb labels:   38
nb blocks:   18963590
nb features: 720617826
```

Bu buyukluk, hem RAM ihtiyacini hem de iteration surelerinin neden uzun oldugunu
aciklar.

### 10.2 Continuous Wapiti Run: `6101352`

Eski continuous run'da Wapiti process'i bolunmeden ilerledi. Lokal log/grafik
ciktilarina gore:

```text
iter 100: token error 1.48%, sequence error 12.84%
iter 110: token error 1.29%, sequence error 11.80%
iter 112: token error 1.27%, sequence error 11.68%
```

Bu run, ayni optimizer process'i icinde devam ettigi icin convergence daha
istikrarliydi. Iteration suresi yaklasik 8-9 dakika bandindaydi.

### 10.3 From-Features / Staged Wapiti Run: `6103492`

Feature generation beklememek ve ara model alabilmek icin
`TrainWapitiFromFeatures.java` ve `train_citation_from_features.sbatch`
hazirlandi. Bu yontem daha once uretilmis `citation*.train` feature dosyasini
kullanarak direkt Wapiti training yapar.

Script her stage sonunda modeli checkpoint olarak kopyalar:

```text
grobid-home/models/citation/checkpoints/
```

Ilk staged ayar:

```text
ITER_PER_STAGE=25
TOTAL_STAGES=8
WAPITI_THREADS=40
partition=barbun
mem=192G
```

Bu yontem checkpoint uretse de onemli bir dezavantaj ortaya cikti: Wapiti
`-m model` ile agirliklari yuklese bile L-BFGS optimizer history'sini aynen
korumaz. Her stage basinda line-search/curvature bilgisi yeniden kurulur. Bu
nedenle stage baslarinda token error artisi goruldu ve convergence continuous
run'a gore belirgin yavasladi.

Karsilastirma:

```text
Continuous 6101352:
iter 25  token error 16.76%
iter 112 token error 1.27%

Staged 6103492:
stage 1 iter 25 / global 25   token error 16.76%
stage 2 iter 1  / global 26   token error 18.07%
stage 5 iter 25 / global 125  token error 11.13%
stage 6 iter 9  / global 134  token error 10.74%
```

Ilk 25 iteration'in birebir ayni olmasi data'nin ayni oldugunu gosterdi. Fark
training stratejisinden kaynaklandi. Sonuc: Wapiti icin 25 iteration stage cok
kisa. Checkpoint isteniyorsa stage uzunlugu 200 gibi daha buyuk tutulmali veya
continuous run tercih edilmeli.

### 10.4 Full DeLFT Citation GPU Denemesi: `6116002`

Lightweight olmayan GROBID citation modeli icin ayrica DeLFT engine denemesi
hazirlandi. Mevcut Wapiti job'a dokunmamak icin izole source tree olusturuldu:

```text
/arf/scratch/isonal/grobid-training/grobid-source-full-citation
```

Kurulumda yapilanlar:

- `grobid-full.yaml` kullanilarak citation engine `delft` olacak sekilde ayrildi.
- DeLFT source `/arf/scratch/isonal/grobid-training/delft` altina kuruldu.
- Python venv `/arf/scratch/isonal/grobid-training/delft-venv` altinda hazirlandi.
- TensorFlow/DeLFT runtime paketleri kuruldu.
- GloVe LMDB embedding cache onceden indirildi/hazirlandi.
- GPU job scripti `akya-cuda` icin cluster kuralina uygun hale getirildi:

```text
partition=akya-cuda
gres=gpu:1
cpus-per-task=10
mem=90G
time=3-00:00:00
```

DeLFT tarafinda Wapiti'deki `maxIter` veya 25-stage mantigi birebir yoktur.
Stok GROBID DeLFT training kendi neural training loop'unu kullanir ve model
output'unu bitiste `citation-BidLSTM_CRF_FEATURES` altina yazar.

## 11. Dashboard ve Izleme

Training loglarini takip etmek icin iki yol kuruldu.

Birinci yol lokal/SSH tabanli dashboard:

```text
live_wapiti_dashboard.py
```

Bu server Wapiti logunu parse edip objective, token error, sequence error ve
iteration surelerini gosterir. `--stream-remote` modunda remote log icin tek
SSH `tail -F` stream'i acar; browser ise SSE endpoint'i uzerinden yeni veri
geldikce guncellenir.

Ikinci ve daha kalici yol GitHub Pages dashboard'dur:

```text
https://isikgirayedu.github.io/grobid-dashboard/
```

Bu modelde TRUBA uzerinde `publish_github_dashboard_on_log.sh` calisir. Script
`tail -F` ile Wapiti logunu dinler. Yeni iteration veya checkpoint/stage satiri
gorunce `generate_dashboard_progress.py` ile `progress.json` uretir ve
GitHub repo'ya push eder. Site statik oldugu icin browser tarafinda server push
yoktur; ancak TRUBA -> GitHub guncellemesi belirli aralikla degil log event'iyle
tetiklenir.

Dashboard'a ayrica `experiments.html` sayfasi eklendi. Bu sayfada Wapiti staged
run, clean-date corpus gate ve full DeLFT GPU run ayri experiment olarak
listelenir.

## 12. 22 Temmuz 2026 Clean Date/Year Duzeltmesi

300 iteration sonunda alinan local test sonucu kotu cikinca training logundan
once corpus kalitesi kontrol edildi. Ana hata iteration sayisi degil, otomatik
projeksiyonda yayin yilinin cok sayida referansta `author` icinde kalmasiydi.
Bu durum modele author span'ini fazla genis ogretiyor ve `date` etiketini
zayiflatiyordu.

Yapilan kod degisikligi:

- TR Dizin `reference.year` birincil yayin yili kabul edildi.
- Yil author span'i icindeyse author yildan once kesilip yil ayri `<date>` olarak
  basildi.
- DOI ve URL icindeki 4 haneli sayilar date adayi olmaktan cikarildi.
- `Retrieved 2022, 3 Haziran` gibi erisim tarihi ifadeleri publication date
  olarak etiketlenmedi.
- Author span title baslangicina kadar korlemesine genislemek yerine yil paterni
  gorunce yildan once bitirildi.

Eklenen kalite kontrol scripti:

```bash
python3 qa_trdizin_citation_corpus.py \
  --corpus-dir trdizin_full_reference_training_clean_date_pilot_v4/citation_corpus \
  --match-report trdizin_full_reference_training_clean_date_pilot_v4/match_report.jsonl \
  --out-json trdizin_full_reference_training_clean_date_pilot_v4/reports/corpus_qa.json \
  --out-md trdizin_full_reference_training_clean_date_pilot_v4/reports/corpus_qa.md \
  --fail-on-author-year-ratio-above 0.05 \
  --fail-on-date-coverage-below 0.80
```

Gate sonucu:

| Metrik | Eski corpus | Clean-date pilot v4 |
| --- | ---: | ---: |
| Referans sayisi | 306,953 | 6,866 |
| Date coverage | 0.3678 | 0.9744 |
| Date-year coverage | 0.3634 | 0.9744 |
| Author icinde kalan yil orani | 0.6245 | 0.0028 |
| Any-year-no-date orani | 0.6255 | 0.0224 |
| Empty label node | 0 | 0 |

Pilot `trdizin_full_reference_training_clean_date_pilot_v4` altinda tutuldu ve
gate'i gecti. Bu sonuc full training'e dogrudan gecmek icin yeterli degil; once
ayni kuralla 10k corpus yeniden uretilecek, QA gate tekrar calisacak, sonra
ayni GROBID surumuyle eski/yeni model karsilastirilacak.

Training ile local evaluation surum uyumu icin `0.9.0-crf` Docker sonucu nihai
karar kaynagi olmaktan cikarildi. Yerelde `../grobid-source` agacindan
`0.9.1-SNAPSHOT` CRF imaji build eden script eklendi:

```bash
./build_grobid_snapshot_crf_docker.sh
PORT=8071 CONTAINER_NAME=grobid-trdizin-new-model-snapshot \
  ./start_grobid_new_model_docker.sh
```

Snapshot servis ayaga kalktiktan sonra ilk 20 test dokumaninda smoke
karsilastirma yapildi:

```bash
GROBID_URL=http://127.0.0.1:8071 LIMIT=20 WORKERS=1 \
  RUN_ROOT=trdizin_model_comparison_snapshot_smoke \
  ./run_local_process_references_comparison.sh
```

Sonuc:

| Metrik | Baseline cached | `6118781` snapshot model |
| --- | ---: | ---: |
| Good documents | 20/20 | 19/20 |
| Reference match rate | 0.9732 | 0.9662 |
| Date coverage | 0.9820 | 0.4017 |
| Year accuracy | 0.9696 | 0.3946 |

Author icinde kalan yil post-process ile date gibi sayildiginda candidate
`date coverage` 0.4680, `year accuracy` 0.4600 oldu ve 55 referans author
alanindan kurtarildi. Bu iyilesme problemi acikliyor ama cozmuyor; baseline
halen cok onde.

Bu smoke, surum uyumu saglandiktan sonra bile mevcut `6118781` modelinin
date/year alaninda kullanilabilir olmadigini dogruladi. Bu beklenen bir durum:
model, clean-date duzeltmesinden onceki problemli corpus ile egitilmisti.

Clean-date mantigi daha sonra sabit `good_ids.txt` 10k evrenine uygulandi.
Final QA gate sonucu:

| Metrik | Clean good10k |
| --- | ---: |
| Dosya | 10,000 |
| Referans | 342,078 |
| Author coverage | 0.9820 |
| Title coverage | 0.9989 |
| Article title coverage | 0.7928 |
| Journal title coverage | 0.7328 |
| Book title coverage | 0.2422 |
| Scope coverage | 0.8106 |
| DOI coverage | 0.2991 |
| URL coverage | 0.0412 |
| Date coverage | 0.9705 |
| Author icinde kalan yil orani | 0.0021 |

Split sonucu:

```text
train: 9000 XML, 307655 references
dev:   500 XML, 17229 references
test:  500 XML, 17194 references
bundle: trdizin_full_reference_training_clean_date_good10k/trdizin_citation_split_training_bundle.tar.gz
```

## 13. Ogrendigimiz Teknik Noktalar

1. TR Dizin referanslari GROBID citation modeli icin kullanilabilir bir raw
   ground truth kaynagi sagliyor.
2. Alan etiketi dogrudan TR Dizin'den gelmedigi icin GROBID'in mevcut TEI
   alanlarini projekte etmek gerekiyor.
3. Fuzzy raw referans eslesmesi olmadan alan projeksiyonu riskli; bu nedenle
   `match_threshold` ve `review_queue` kritik.
4. `min_labeled_spans` ve `min_labeled_char_ratio` filtreleri corpus kalitesini
   korumak icin gerekli.
5. GROBID/Wapiti citation training feature matrisi cok buyuk; RAM ve sure
   ihtiyaci yuksek.
6. Wapiti continuous training ile staged incremental training ayni kaliteyi ayni
   iteration sayisinda vermiyor. Kisa stage'ler optimizer history kaybi yuzunden
   convergence'i bozuyor.
7. Ara checkpoint ihtiyaci varsa Wapiti'de stage boyu daha uzun tutulmali; 25
   iteration pratikte fazla kisa.
8. Full DeLFT denemesi Wapiti'den ayri source tree'de tutulmali; ayni
   `grobid-source` icinde engine/config degistirmek aktif Wapiti run'ini riske
   sokar.
9. Otomatik projeksiyonla uretilecek corpus'ta date/author QA gate'i olmadan
   full training'e gecmek riskli; training logu iyi gorunse bile local model
   yil alaninda gerileyebilir.

## 14. Bilinen Riskler ve Sinirlar

- TR Dizin `context` metni her zaman PDF'teki kaynakca metniyle birebir ayni
  olmayabilir. Noktalama, kisaltma, Unicode ve siralama farklari olabilir.
- GROBID mevcut model bir alani yanlis etiketlediyse, projeksiyon bu yanlis
  etiketi TR Dizin metnine tasiyabilir.
- `weak_field_projection` review queue'su temizlenmeden corpus tamamen
  hatasiz kabul edilmemeli.
- Sequence error, token error'dan cok daha sert bir metriktir; tek referansta
  herhangi bir alan hatasi tum sequence'i hatali sayabilir.
- Dashboard'daki ETA kaba tahmindir; stage baslari, checkpoint yazimi, Slurm
  node yuku ve optimizer davranisi tahmini bozabilir.
- DeLFT run Wapiti ile ayni iteration/checkpoint semantigine sahip degildir.
- Clean-date pilot kalite kapisini gecmis olsa da 10k full rebuild ve held-out
  model evaluation yapilmadan final model kabul edilmemeli.

## 15. Tekrar Uretim Icin Ana Komutlar

TR Dizin ground truth ile corrected citation corpus uretmek:

```bash
cd /Users/isikgiray/Desktop/ULAKBİM/grobid
python3 build_trdizin_corrected_reference_corpus.py \
  --grobid-tei-dir grobid_references_tei \
  --out-dir trdizin_corrected_reference_corpus \
  --workers 8
```

Test icin:

```bash
python3 build_trdizin_corrected_reference_corpus.py \
  --limit 20 \
  --overwrite
```

Corpus archive almak:

```bash
tar -czf trdizin_citation_corpus.tar.gz \
  trdizin_corrected_reference_corpus/citation_corpus
```

TRUBA'da staged Wapiti from-features run baslatmak:

```bash
cd /arf/scratch/isonal/grobid-training/grobid-source
sbatch --export=ALL,ITER_PER_STAGE=200,TOTAL_STAGES=15 \
  train_citation_from_features.sbatch
```

Full DeLFT GPU run baslatmak:

```bash
cd /arf/scratch/isonal/grobid-training/grobid-source-full-citation
DELFT_HOME=/arf/scratch/isonal/grobid-training/delft \
DELFT_VENV=/arf/scratch/isonal/grobid-training/delft-venv \
sbatch train_citation_full_delft_gpu.sbatch
```

Job kontrol:

```bash
squeue -u isonal
squeue -j <JOBID> -o "%i|%j|%T|%M|%l|%P|%N|%R|%S"
```

Wapiti log kontrol:

```bash
grep -E '^  \[[[:space:]]*[0-9]+\]' train_citation_from_features.<JOBID>.err | tail -20
```

Clean-date full rebuild:

```bash
python3 build_trdizin_corrected_reference_corpus.py \
  --ids sadece_idler.txt \
  --grobid-tei-dir trdizin_full_reference_training/grobid_process_references_tei \
  --out-dir trdizin_full_reference_training_clean_date_10k \
  --ground-truth-dir trdizin_full_reference_training/trdizin_ground_truth \
  --workers 8 \
  --overwrite \
  --alignment-window 8 \
  --global-fallback

python3 qa_trdizin_citation_corpus.py \
  --corpus-dir trdizin_full_reference_training_clean_date_10k/citation_corpus \
  --match-report trdizin_full_reference_training_clean_date_10k/match_report.jsonl \
  --out-json trdizin_full_reference_training_clean_date_10k/reports/corpus_qa.json \
  --out-md trdizin_full_reference_training_clean_date_10k/reports/corpus_qa.md \
  --fail-on-author-year-ratio-above 0.05 \
  --fail-on-date-coverage-below 0.80
```

## 16. Onerilen Sonraki Adimlar

1. Clean-date mantigiyla 10k corpus yeniden uretilmeli ve QA gate
   tekrarlanmali.
2. `review_queue.csv` icindeki en yaygin hata tipleri gruplanmali.
3. `weak_field_projection` durumlari icin title/date/DOI gibi guvenilir alanlar
   bazinda daha iyi projection heuristics eklenmeli.
4. Wapiti staged run tekrar acilacaksa `ITER_PER_STAGE=200` veya daha yuksek
   denenmeli.
5. Continuous Wapiti run ile staged run ayni validation set uzerinde
   karsilastirilmali.
6. DeLFT GPU run basladiginda log formati ayrica parse edilip dashboard'a ikinci
   metrik kaynagi olarak eklenmeli.
7. Final model sadece training log metrikleriyle degil, elde tutulmus TR Dizin
   test seti uzerinde alan bazli precision/recall ile degerlendirilmeli.
