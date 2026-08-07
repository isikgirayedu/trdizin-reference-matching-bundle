# TR Dizin Reference Training Notes

Bu klasor TR Dizin referanslarini ground truth kabul edip GROBID `citation` modeli icin training corpus uretmek ve TRUBA uzerinde egitimi takip etmek icin kullaniliyor.

## Yerel Dosyalar

- `build_trdizin_corrected_reference_corpus.py`: TR Dizin referanslarini cekip GROBID referans TEI ciktisindaki etiketleri TR Dizin raw referans metnine projekte eder.
- `qa_trdizin_citation_corpus.py`: Uretilen citation corpus icin date coverage, author icinde kalan yil ve weak label QA metriklerini raporlar.
- `build_grobid_snapshot_crf_docker.sh`: Local `../grobid-source` agacindan training ile uyumlu `0.9.1-SNAPSHOT` CRF Docker image'i build eder.
- `trdizin_corrected_reference_corpus/citation_corpus/`: GROBID citation trainer corpus dosyalari. Su an 9689 XML var.
- `train_citation.sbatch`: TRUBA/Slurm uzerinde `train_citation` baslatan job scripti.
- `train_citation_split_300.sbatch`: 9000 dokumanlik train split uzerinden 300 iteration citation egitimi baslatir.
- `install_and_submit_citation_split_300.sh`: TRUBA'da train split corpus'unu kurar ve split-aware job'u submit eder.
- `package_citation_split_training_bundle.sh`: Split arshivlerini ve TRUBA scriptlerini tek transfer paketine toplar.
- `plot_wapiti_training_log.py`: Wapiti iteration logundan CSV ve PNG grafik uretir.
- `train_citation.<JOBID>.err`: Wapiti training ilerleme logu.
- `train_citation.<JOBID>.png`: Training grafigi.

## Corpus Uretme

Mevcut GROBID `processReferences` TEI dosyalarindan TR Dizin ground truth ile citation corpus uretmek icin:

```bash
cd /Users/isikgiray/Desktop/ULAKBİM/grobid
python3 build_trdizin_corrected_reference_corpus.py \
  --grobid-tei-dir grobid_references_tei \
  --out-dir trdizin_corrected_reference_corpus \
  --workers 8
```

Test icin az sayida id:

```bash
python3 build_trdizin_corrected_reference_corpus.py --limit 20 --overwrite
```

## Clean Date/Year Corpus Gate

22 Temmuz 2026 duzeltmesiyle publication year artik author icinden ayrilip
`<date>` olarak basiliyor; URL/DOI ve erisim tarihi icindeki yillar date olarak
kullanilmiyor.

Mevcut problemli corpus QA:

```bash
python3 qa_trdizin_citation_corpus.py \
  --corpus-dir /Users/isikgiray/Desktop/ULAKBİM/grobid-source/grobid-trainer/resources/dataset/citation/corpus \
  --out-json trdizin_full_reference_training/reports/current_corpus_qa_before_fix.json \
  --out-md trdizin_full_reference_training/reports/current_corpus_qa_before_fix.md
```

200 dokumanlik clean-date pilot:

```bash
python3 build_trdizin_corrected_reference_corpus.py \
  --ids trdizin_full_reference_training/splits/test/ids.txt \
  --grobid-tei-dir trdizin_full_reference_training/grobid_process_references_tei \
  --out-dir trdizin_full_reference_training_clean_date_pilot_v4 \
  --ground-truth-dir trdizin_full_reference_training/trdizin_ground_truth \
  --workers 4 \
  --limit 200 \
  --overwrite \
  --alignment-window 8 \
  --global-fallback

python3 qa_trdizin_citation_corpus.py \
  --corpus-dir trdizin_full_reference_training_clean_date_pilot_v4/citation_corpus \
  --match-report trdizin_full_reference_training_clean_date_pilot_v4/match_report.jsonl \
  --out-json trdizin_full_reference_training_clean_date_pilot_v4/reports/corpus_qa.json \
  --out-md trdizin_full_reference_training_clean_date_pilot_v4/reports/corpus_qa.md \
  --fail-on-author-year-ratio-above 0.05 \
  --fail-on-date-coverage-below 0.80
```

Pilot gate sonucu:

```text
before: references=306953, date_coverage=0.3678, author_year_ratio=0.6245
after:  references=6866,   date_coverage=0.9744, author_year_ratio=0.0028
full:   references=342078, date_coverage=0.9705, author_year_ratio=0.0021
```

Clean good10k alan coverage ozeti:

```text
author=0.9820
title_any=0.9989
article_title=0.7928
journal_title=0.7328
book_title=0.2422
scope=0.8106
doi=0.2991
url=0.0412
date=0.9705
```

Full rebuild icin ayni gate korunacak:

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

Good set ile uretilen final clean-date ciktilar:

```text
trdizin_full_reference_training_clean_date_good10k/citation_corpus
trdizin_full_reference_training_clean_date_good10k/reports/corpus_qa.md
trdizin_full_reference_training_clean_date_good10k/splits
trdizin_full_reference_training_clean_date_good10k/trdizin_citation_split_training_bundle.tar.gz
```

Clean-date split:

```text
train: 9000 XML, 307655 references
dev:   500 XML, 17229 references
test:  500 XML, 17194 references
```

Archive almak icin:

```bash
tar -czf trdizin_citation_corpus.tar.gz trdizin_corrected_reference_corpus/citation_corpus
```

## Remote Kurulum

TRUBA remote path:

```bash
/arf/scratch/isonal/grobid-training/grobid-source
```

Remote GROBID corpus path:

```bash
/arf/scratch/isonal/grobid-training/grobid-source/grobid-trainer/resources/dataset/citation/corpus
```

Remote Java 21 path:

```bash
/arf/scratch/isonal/grobid-training/jdk-21
```

## Egitimi Baslatma

Remote'a gir:

```bash
ssh isonal@172.16.6.11
cd /arf/scratch/isonal/grobid-training/grobid-source
```

Job baslat:

```bash
sbatch train_citation.sbatch
```

Mevcut script kaynaklari:

```text
partition: barbun
nodes: 1
tasks: 1
cpus-per-task: 40
mem: 192G
time: 2-00:00:00
```

## Split-Aware 10k Citation Egitimi

Guncel onerilen akista 10k corpus komple egitime verilmez. `train` split
GROBID'in citation corpus klasorune kurulur; `dev` ve `test` arshivleri held-out
evaluation icin ayri tutulur.

Yerelde bundle uret:

```bash
cd /Users/isikgiray/Desktop/ULAKBİM/grobid
./package_citation_split_training_bundle.sh
```

Uretilen paket:

```text
trdizin_full_reference_training/trdizin_citation_split_training_bundle.tar.gz
```

TRUBA'ya kopyala:

```bash
scp trdizin_full_reference_training/trdizin_citation_split_training_bundle.tar.gz \
  isonal@172.16.6.11:/arf/scratch/isonal/grobid-training/grobid-source/
```

TRUBA'da paketi ac:

```bash
ssh isonal@172.16.6.11
cd /arf/scratch/isonal/grobid-training/grobid-source
tar -xzf trdizin_citation_split_training_bundle.tar.gz --strip-components=1
```

Once dry-run install:

```bash
SUBMIT=0 ./install_and_submit_citation_split_300.sh
```

Bu komut `9000/500/500` arshiv sayilarini kontrol eder, sadece `train`
splitindeki 9000 XML'i GROBID citation corpus klasorune kurar ve submit etmez.

Job submit:

```bash
./install_and_submit_citation_split_300.sh
```

Iteration sayisini override etmek icin:

```bash
MAX_ITER=500 ./install_and_submit_citation_split_300.sh
```

Beklenen split sayilari:

```text
train: 9000 XML
dev: 500 XML
test: 500 XML
```

Dev/test arshivleri su klasorde tutulur ama training corpus'una kurulmaz:

```text
trdizin_citation_splits/
```

20 Temmuz 2026 split-aware run:

```text
job_id=6118678 iptal edildi: 40 core ile cluster verim uyarisi verdi
job_id=6118754 iptal edildi: feature generation tekrarina girdi
job_id=6118781
state=COMPLETED
elapsed=1-05:17:39
exit_code=0:0
script=train_citation_continuous_from_features.sbatch
cpus-per-task=20
mem=128G
train XML=9000
MAX_ITER=300
WAPITI_THREADS=20
PRECOMPUTED_TRAIN=/arf/scratch/isonal/grobid-training/grobid-source/grobid-home/tmp/old_feature_runs/citation1093144200238648198.train.before-trdizin-split-20260720153647
first_iteration=635.49s (~10.6 min)
steady_iteration=326-335s (~5.5 min)
bench40_job_id=6118816 iptal edildi: 40 thread 20 thread'den hizli olmadi (iter1=768.33s, iter2=387.20s)
remote out=train_citation_continuous_from_features.6118781.out
remote err=train_citation_continuous_from_features.6118781.err
final iteration=300
final token error=0.76%
final sequence error=8.72%
remote final model=grobid-home/models/citation/model.wapiti
remote checkpoint=grobid-home/models/citation/checkpoints/model.continuous.iter0300.6118781.20260721205823.wapiti
local artifact=remote_training_artifacts/6118781/model.continuous.iter0300.6118781.20260721205823.wapiti
model sha256=9dc16203efd6356054297a57bbd7d118f291b3cf25f3c275436d6379a043754c
```

Gozlemler ve kararlar:

- 40 core ile baslayan ilk run (`6118678`) cluster verim uyarisi verdi; bu is iptal edildi.
- Barbun kuyrugu 8 core kabul etmedigi icin minimum pratik submit 20 core oldu.
- 20 core normal split job (`6118754`) feature generation'i bastan tekrar ettigi icin iptal edildi.
- Tamamlanmis train feature dosyasi kullanildiginda Wapiti yukleme yaklasik 8 dakika surdu ve L-BFGS'e direkt gecildi.
- Aktif run (`6118781`) 20 CPU / 128G RAM ile calisiyor; gozlenen RSS 60-98G bandina cikti, yani RAM siniri degil CPU/thread davranisi belirleyici.
- Ilk iteration pahaliydi: 635.49s (~10.6 dk). Sonraki oturan tempo 326-335s (~5.5 dk/iteration).
- 40 thread benchmark (`6118816`) model kurmadan denendi (`INSTALL_MODEL=0`) ve 20 thread'den hizli olmadi: iter1=768.33s, iter2=387.20s. Bu nedenle iptal edildi.
- Son karar: ana egitim 20 thread ile devam etmeli; bos CPU ayni modelin tek iteration'ini anlamli hizlandirmadi. Bos kaynak ancak ayri hyperparameter/ablation denemeleri icin kullanilmali.
- `github_dashboard/progress.json` artik `6118781` run'ini izler; iteration ve ETA degerleri publisher yeni log satiri bastikca degisir.
- `github_dashboard/progress.json` 22 Temmuz 2026 itibariyla `6118781` icin `COMPLETED` durumuna guncellendi ve GitHub Pages'e push edildi.

## Full DeLFT Citation Egitimi

Su anki `6118781` Wapiti/from-features job'u calisirken full DeLFT denemesi ayni
`grobid-source` icinde baslatilmamali. Izole kopya hazirla:

```bash
cd /arf/scratch/isonal/grobid-training
bash setup_full_delft_citation_run.sh
```

Sonra GPU job'unu manuel submit et:

```bash
cd /arf/scratch/isonal/grobid-training/grobid-source-full-citation
sbatch --export=ALL,DELFT_HOME=/arf/scratch/isonal/grobid-training/delft,DELFT_VENV=/arf/scratch/isonal/grobid-training/delft-venv,EXPECTED_CORPUS_COUNT=9000 \
  train_citation_full_delft_gpu.sbatch
```

Varsayilan GPU partition `akya-cuda`. Gerekirse submit ederken degistir:

```bash
sbatch --partition=barbun-cuda train_citation_full_delft_gpu.sbatch
```

Not: `grobid-full.yaml` citation modelini `engine: "delft"` yapar. Bu mod Wapiti'nin
`-maxIter`/25-stage mantigini kullanmaz; GROBID kodunda `maxIter` sadece Wapiti
trainer tarafinda isler, DeLFT trainer tarafinda ignore edilir. Bu yuzden 200
iteration checkpoint ayni sekilde yok; stok DeLFT run final modeli bitince
`grobid-home/models/citation-BidLSTM_CRF_FEATURES` altina yazar.

20 Temmuz 2026 guncel GPU run:

```text
previous_gpu_job=6116002 aktif degildi / superseded
job_id=6119305
script=train_citation_full_delft_gpu.sbatch
partition=akya-cuda
state=PENDING (Priority) at submit
resources=1 GPU, 10 CPU, 128G RAM
workdir=/arf/scratch/isonal/grobid-training/grobid-source-full-citation
corpus XML=9000
engine=delft
DELFT_VENV=/arf/scratch/isonal/grobid-training/delft-venv
remote out=train_citation_full_delft.6119305.out
remote err=train_citation_full_delft.6119305.err
```

Not: `akya-cuda` 1 GPU icin 10 CPU istiyor. 20 CPU / 1 GPU submit reddedildi;
2 GPU istemek de bu tek DeLFT training icin anlamli degil. Bu yuzden GPU run
10 CPU / 1 GPU ile, fakat guncel 9000 XML train split ve 128G RAM ile gonderildi.

Eger preflight `DeLFT install directory not found` derse DeLFT runtime henuz
hazir degildir. Ayrı venv ve DeLFT source kurmak icin:

```bash
cd /arf/scratch/isonal/grobid-training
bash install_delft_runtime_truba.sh
```

Embedding cache de hazirlansin istersen, daha uzun surer ve cok disk kullanir:

```bash
cd /arf/scratch/isonal/grobid-training
PRELOAD_EMBEDDINGS=1 bash install_delft_runtime_truba.sh
```

## Job Takibi

Kendi joblarini listele:

```bash
squeue -u isonal
```

Belirli job:

```bash
squeue -j <JOBID>
```

Log takip:

```bash
cd /arf/scratch/isonal/grobid-training/grobid-source
tail -f train_citation.<JOBID>.err
```

Out ve err beraber:

```bash
tail -f train_citation.<JOBID>.out train_citation.<JOBID>.err
```

CPU/RAM:

```bash
sstat -j <JOBID>.batch --format=JobID,AveCPU,AveRSS,MaxRSS
```

Job bittiyse ayrintili durum:

```bash
sacct -j <JOBID> --format=JobID,JobName%18,Partition,State,Elapsed,Timelimit,AllocCPUS,MaxRSS,ExitCode
```

Iteration satirlari:

```bash
grep -E '^  \[[[:space:]]*[0-9]+\]' train_citation.<JOBID>.err | tail -20
```

Basari/hata:

```bash
grep -iE 'BUILD SUCCESSFUL|BUILD FAILED|OutOfMemory|oom|Killed|Exception' \
  train_citation.<JOBID>.out train_citation.<JOBID>.err
```

## Grafik Uretme

Onemli: `plot_wapiti_training_log.py` dosyasi `grobid-source` icinde degil, yerel workspace icinde:

```bash
/Users/isikgiray/Desktop/ULAKBİM/grobid/plot_wapiti_training_log.py
```

Dogru kullanim:

```bash
cd /Users/isikgiray/Desktop/ULAKBİM/grobid
scp isonal@172.16.6.11:/arf/scratch/isonal/grobid-training/grobid-source/train_citation.<JOBID>.err .
python3 plot_wapiti_training_log.py train_citation.<JOBID>.err --target-iteration 150
open train_citation.<JOBID>.png
```

Ornek:

```bash
cd /Users/isikgiray/Desktop/ULAKBİM/grobid
scp isonal@172.16.6.11:/arf/scratch/isonal/grobid-training/grobid-source/train_citation.6101352.err .
python3 plot_wapiti_training_log.py train_citation.6101352.err --target-iteration 150
open train_citation.6101352.png
```

Script su dosyalari uretir:

```text
train_citation.<JOBID>.csv
train_citation.<JOBID>.png
```

## Canli Dashboard

Streamlit kurulu olmadigi icin dashboard standart Python HTTP server ile calisir. Ek paket gerektirmez.

Dashboard dosyasi:

```bash
/Users/isikgiray/Desktop/ULAKBİM/grobid/live_wapiti_dashboard.py
```

Sadece eldeki lokal log dosyasini izlemek icin:

```bash
cd /Users/isikgiray/Desktop/ULAKBİM/grobid
python3 live_wapiti_dashboard.py \
  --job-id 6101352 \
  --log-file train_citation.6101352.err \
  --target-iteration 150
```

Sonra browser:

```text
http://127.0.0.1:8765
```

Remote logu canli cekmek icin SSH ControlMaster ac. Bu parola sadece bir kere ister:

```bash
ssh -MNf \
  -o ControlMaster=yes \
  -o ControlPath=/tmp/grobid-truba-ctrl \
  -o ControlPersist=12h \
  isonal@172.16.6.11
```

Sonra dashboard'u remote sync ile baslat:

```bash
cd /Users/isikgiray/Desktop/ULAKBİM/grobid
python3 live_wapiti_dashboard.py \
  --job-id 6101352 \
  --log-file train_citation.6101352.err \
  --ssh-control-path /tmp/grobid-truba-ctrl \
  --sync \
  --target-iteration 150
```

Mevcut split continuous/from-features job icin polling yerine tek SSH `tail -F` stream'i kullanan komut:

```bash
cd /Users/isikgiray/Desktop/ULAKBİM/grobid
python3 live_wapiti_dashboard.py \
  --job-id 6118781 \
  --log-file train_citation_continuous_from_features.6118781.err \
  --remote-log-template 'train_citation_continuous_from_features.{job_id}.err' \
  --ssh-control-path /tmp/grobid-truba-ctrl \
  --sync \
  --stream-remote \
  --target-iteration 300 \
  --stage-size 0
```

`--stream-remote` modunda server remote log icin tek SSH baglantisi acar. Browser ise `/events`
SSE endpoint'ine baglanir; 30 saniyede bir sayfa/API refresh yapmak yerine veri degistikce UI
guncellenir.

En rahat takip yontemi public tunnel kullanmadan SSH port-forward acmak:

```bash
ssh -f -N \
  -o ExitOnForwardFailure=yes \
  -L 8765:127.0.0.1:8765 \
  isonal@172.16.6.11
```

Sonra lokal tarayicida:

```text
http://127.0.0.1:8765
```

Bu yontemde URL degismez. Public degildir; sadece port-forward acik olan makineden erisilir.

Arka planda calistirmak icin:

```bash
screen -dmS grobid_dashboard_6118781 python3 -u live_wapiti_dashboard.py \
  --job-id 6118781 \
  --log-file train_citation_continuous_from_features.6118781.err \
  --remote-log-template 'train_citation_continuous_from_features.{job_id}.err' \
  --ssh-control-path /tmp/grobid-truba-ctrl \
  --sync \
  --stream-remote \
  --target-iteration 300 \
  --stage-size 0 \
  --quiet
```

## Ucretsiz Public Dashboard URL'i

Kalici public takip icin asil URL GitHub Pages uzerinden acilir:

```text
https://isikgirayedu.github.io/grobid-dashboard/
```

Bu sayfa Mac'e bagli degildir. TRUBA yeni Wapiti iteration/checkpoint log satiri urettikce
`progress.json` dosyasi GitHub'a push edilir; GitHub Pages de `gh-pages` branch'inden servis eder.

Eski `localhost.run` tunnel yontemi sadece gecici/alternatif takip icindir. URL degisebilir:

```text
https://<random>.lhr.life
```

Remote process kontrol:

```bash
ssh isonal@172.16.6.11
cd /arf/scratch/isonal/grobid-training/grobid-source
screen -ls
grep -Eo 'https://[a-z0-9]+\.lhr\.life' localhostrun_dashboard.log | tail -1
```

Remote dashboard'u yeniden baslatmak icin:

```bash
cd /arf/scratch/isonal/grobid-training/grobid-source
screen -S grobid_dashboard_remote -X quit 2>/dev/null || true
screen -dmS grobid_dashboard_remote python3 -u live_wapiti_dashboard.py \
  --job-id 6118781 \
  --log-file train_citation_continuous_from_features.6118781.err \
  --remote-host local \
  --target-iteration 300 \
  --stage-size 0 \
  --host 127.0.0.1 \
  --port 8765 \
  --quiet
```

Remote public tunnel'i yeniden baslatmak icin:

```bash
cd /arf/scratch/isonal/grobid-training/grobid-source
screen -S grobid_lhr_tunnel -X quit 2>/dev/null || true
: > localhostrun_dashboard.log
screen -dmS grobid_lhr_tunnel /bin/bash --noprofile --norc ./run_lhr_tunnel.sh
grep -Eo 'https://[a-z0-9]+\.lhr\.life' localhostrun_dashboard.log | tail -1
```

Kapatmak icin:

```bash
screen -S grobid_lhr_tunnel -X quit
screen -S grobid_dashboard_remote -X quit
```

## GitHub Pages Dashboard

Mac'ten tamamen bagimsiz ve sabit URL'li takip icin GitHub Pages kullanilabilir. Bu modelde
site statiktir; TRUBA yeni Wapiti iteration satiri uretince `progress.json` dosyasini yeniden
uretir ve GitHub repo'ya push eder. Yani GitHub'a guncelleme belirli aralikla degil, log event'i
ile gider.

Aktif URL:

```text
https://isikgirayedu.github.io/grobid-dashboard/
```

Aktif repo:

```text
https://github.com/isikgirayedu/grobid-dashboard
```

Hazirlanan dosyalar:

```bash
github_dashboard/index.html
github_dashboard/progress.json
generate_dashboard_progress.py
publish_github_dashboard_on_log.sh
```

Remote kopyalar:

```bash
/arf/scratch/isonal/grobid-training/grobid-dashboard-pages
/arf/scratch/isonal/grobid-training/grobid-source/generate_dashboard_progress.py
/arf/scratch/isonal/grobid-training/grobid-source/publish_github_dashboard_on_log.sh
```

GitHub repo baglandiktan sonra TRUBA'da publisher'i baslat:

```bash
cd /arf/scratch/isonal/grobid-training/grobid-source
screen -S github_dashboard_publisher -X quit 2>/dev/null || true
screen -dmS github_dashboard_publisher ./publish_github_dashboard_on_log.sh
```

Durum kontrol:

```bash
screen -ls
tail -n 40 github_dashboard_publisher.log
```

Publisher varsayilan olarak `tail -F train_citation_continuous_from_features.6118781.err` dinler. Sadece su satirlar gelince
`main` ve `gh-pages` branch'lerine commit/push yapar:

- Wapiti iteration satiri: `[  20] obj=...`
- checkpoint/stage satirlari

Not: GitHub Pages statik hosting oldugu icin browser'a server-side push/SSE yapamaz. TRUBA ->
GitHub update'i event-driven olur; browser son JSON'u gormek icin sayfayi yeniler veya dashboard
icindeki `Refresh` dugmesine basilir.

ControlMaster'i kapatmak icin:

```bash
ssh -S /tmp/grobid-truba-ctrl -O exit isonal@172.16.6.11
```

Dashboard su bilgileri gosterir:

- Slurm state ve elapsed time
- son iteration
- objective
- token/sequence error
- son iteration hizindan hedef iteration ETA
- remote sync hatasi varsa sebebi

## Checkpoint ve Erken Durdurma

Mevcut GROBID/Wapiti train cagrisinda ara checkpoint yok. Model sadece training basariyla bitince yazilir:

```bash
grobid-home/models/citation/model.wapiti
```

Bu yuzden:

- `scancel <JOBID>` mevcut optimizer ilerlemesini kaybettirir.
- Eski `model.wapiti` korunur, yeni model yazilmaz.
- "Su ana kadarki modeli kaydet" gibi bir komut yok.
- Garanti kisa sonuc istenirse bastan daha dusuk `nbMaxIterations` ile kosmak gerekir.

## Gelecek Runlar Icin Chunked Checkpoint

Wapiti kendi basina ara checkpoint yazmiyor. Ama GROBID `TrainerRunner` su parametreleri destekliyor:

```text
-maxIter     Wapiti max iteration
-i           incremental training
-modelPath   custom model path
```

Bu nedenle gelecek run'larda en pratik cozum egitimi parcalara bolmek. Her chunk tamamlaninca valid `model.wapiti` olusur ve checkpoint olarak kopyalanir. Bunun icin script:

```bash
train_citation_chunked.sbatch
```

Remote'a kopyala:

```bash
scp /Users/isikgiray/Desktop/ULAKBİM/grobid/train_citation_chunked.sbatch \
  isonal@172.16.6.11:/arf/scratch/isonal/grobid-training/grobid-source/
```

Ornek: 50 iteration x 4 stage = toplam 200 iteration:

```bash
ssh isonal@172.16.6.11
cd /arf/scratch/isonal/grobid-training/grobid-source
sbatch --export=ALL,ITER_PER_STAGE=50,TOTAL_STAGES=4 train_citation_chunked.sbatch
```

Ornek: sadece hizli 50 iteration model:

```bash
sbatch --export=ALL,ITER_PER_STAGE=50,TOTAL_STAGES=1 train_citation_chunked.sbatch
```

Checkpoint dosyalari:

```bash
ls -lh grobid-home/models/citation/checkpoints/
```

Bu yontemde `scancel` olursa sadece calismakta olan chunk kaybolur. Son tamamlanan chunk'in modeli checkpoint klasorunde kalir.

Not: Mevcut normal `train_citation.sbatch` job'u calisirken ayni model klasorunde chunked job baslatma. Ayni `model.wapiti` uzerinde cakisirlar.

## Prep'i Atlayarak Egitme

Normal `./gradlew train_citation` her seferinde sunu bastan yapar:

```text
TEI corpus -> grobid-home/tmp/citation*.train feature dosyasi -> Wapiti train
```

Prep'i beklememek icin daha once olusmus `citation*.train` dosyasini kullanabiliriz. Bunun icin:

```bash
TrainWapitiFromFeatures.java
train_citation_from_features.sbatch
```

Remote'a zaten kopyalandi. Gelecekte tekrar kopyalamak gerekirse:

```bash
scp /Users/isikgiray/Desktop/ULAKBİM/grobid/TrainWapitiFromFeatures.java \
    /Users/isikgiray/Desktop/ULAKBİM/grobid/train_citation_from_features.sbatch \
    isonal@172.16.6.11:/arf/scratch/isonal/grobid-training/grobid-source/
```

En yeni precomputed feature dosyasini kullanarak 50 iteration kos:

```bash
cd /arf/scratch/isonal/grobid-training/grobid-source
sbatch --export=ALL,MAX_ITER=50 train_citation_from_features.sbatch
```

Belirli feature dosyasini kullanmak icin:

```bash
sbatch --export=ALL,MAX_ITER=50,PRECOMPUTED_TRAIN=/arf/scratch/isonal/grobid-training/grobid-source/grobid-home/tmp/citationXXXX.train \
  train_citation_from_features.sbatch
```

Bu yontem prep'i atlar ama current running job'un optimizer state'inden devam etmez. Sadece eldeki `.train` feature dosyasindan yeni Wapiti training baslatir.

## Checkpoint'ten Model Alma

Chunked run'da her tamamlanan stage sonunda valid model checkpoint olarak kalir:

```bash
grobid-home/models/citation/checkpoints/
```

Istedigin zaman kullanabilecegin model output'u son tamamlanan checkpoint'tir. Ornek:

```bash
cd /arf/scratch/isonal/grobid-training/grobid-source
ls -lh grobid-home/models/citation/checkpoints/
```

Bir checkpoint'i aktif model yapmak icin once mevcut modeli yedekle:

```bash
cp grobid-home/models/citation/model.wapiti \
   grobid-home/models/citation/model.wapiti.before-manual-checkpoint.$(date +%Y%m%d%H%M%S)
```

Sonra istedigin checkpoint'i aktif modele kopyala:

```bash
cp grobid-home/models/citation/checkpoints/model.stage001.iter0050.wapiti \
   grobid-home/models/citation/model.wapiti
```

Sinir: Calismakta olan stage'in ara modeli alinmaz. Sadece tamamlanmis stage checkpoint'i kullanilabilir.

## Controlled Rerun

Mevcut job'u iptal etmek gerekiyorsa:

```bash
scancel <JOBID>
```

Citation max iteration dusurmek icin remote'da `grobid-home/config/grobid.yaml` icindeki citation blogunu degistir:

```yaml
- name: "citation"
  engine: "wapiti"
  wapiti:
    epsilon: 0.00001
    window: 50
    nbMaxIterations: 150
```

Sonra yeniden baslat:

```bash
cd /arf/scratch/isonal/grobid-training/grobid-source
sbatch train_citation.sbatch
```

Not: Full corpus ile 150 iteration bile uzun surebilir. Son olcumde 1 iteration yaklasik 8.5 dakika suruyordu.

## OOM Notu

Ilk deneme `64G` RAM ile OOM oldu:

```text
State: OUT_OF_MEMORY
MaxRSS: ~108G
exit value 137
```

Bu nedenle `train_citation.sbatch` su an `192G` RAM istiyor.

## Model Dosyasi Kontrolu

Model timestamp ve boyut:

```bash
cd /arf/scratch/isonal/grobid-training/grobid-source
ls -lh --time-style=long-iso grobid-home/models/citation/model.wapiti
```

Training basariyla bittiginde logda sunu gormeyi bekle:

```text
BUILD SUCCESSFUL
```

## Held-Out Test Evaluation

`6118781` final modelinin train log metrikleri train feature dosyasi uzerindeki
Wapiti optimizasyon sinyalidir. Asil model kalitesi icin 500 dokumanlik held-out
test split ayri evaluation job'u ile olculur.

Hazirlanan script:

```text
evaluate_citation_6118781_test.sbatch
```

Submit edilen job:

```text
job_id=6125597
partition=barbun
state=COMPLETED
elapsed=00:09:07
exit_code=0:0
time=04:00:00
cpus-per-task=20
mem=128G
model=grobid-home/models/citation/checkpoints/model.continuous.iter0300.6118781.20260721205823.wapiti
test split=trdizin_citation_splits/test.citation_corpus.tar.gz
```

Takip:

```bash
cd /arf/scratch/isonal/grobid-training/grobid-source
squeue -j 6125597
tail -f evaluate_citation_6118781_test.6125597.out evaluate_citation_6118781_test.6125597.err
```

Rapor job bitince burada olur:

```text
trdizin_citation_splits/evaluation_reports/citation_test_6118781.6125597.txt
```

Final held-out test sonucu:

```text
test XML=500
expected instances=16478
field micro avg precision=93.19
field micro avg recall=94.28
field micro avg f1=93.73
field macro avg precision=89.90
field macro avg recall=89.74
field macro avg f1=89.74
instance-level recall=71.84
local report=remote_training_artifacts/6125597/citation_test_6118781.6125597.txt
```

## Local ProcessReferences Model Comparison

Nihai local test, training ile ayni GROBID source surumunden build edilen
`0.9.1-SNAPSHOT` CRF image ile yapilmali. Eski `grobid/grobid:0.9.0-crf`
image sadece hizli smoke test icin kullanilir, final karar icin kullanilmaz.

Matching local image'i build et:

```bash
cd /Users/isikgiray/Desktop/ULAKBİM/grobid
./build_grobid_snapshot_crf_docker.sh
```

Yeni modeli lokal Docker GROBID'e takmak icin:

```bash
./start_grobid_new_model_docker.sh
```

Bu script `remote_training_artifacts/6118781/model.continuous.iter0300.6118781.20260721205823.wapiti`
dosyasini container icindeki `citation/model.wapiti` ustune read-only mount eder
ve default olarak `grobid-local:0.9.1-snapshot-crf` image'ini kullanir. Docker
Desktop bellegi yetmezse container `OOMKilled=true` ile kapanabilir; bu durumda
diger GROBID container'larini kapatmak veya Docker bellegini artirmak gerekir.

Eski cache ile yeni modelin `processReferences` ciktilarini karsilastirma:

```bash
LIMIT=100 WORKERS=2 ./run_local_process_references_comparison.sh
```

20 Temmuz test splitinden ilk 100 dokuman uzerinde 22 Temmuz 2026 sonucu:

```text
baseline good documents=100/100
candidate good documents=97/100
baseline reference match rate=0.9761
candidate reference match rate=0.9463
baseline avg document match ratio=0.9797
candidate avg document match ratio=0.9659
article_title coverage=0.7476 -> 0.7018
journal_title coverage=0.7060 -> 0.6794
date coverage=0.9881 -> 0.3751
doi coverage=0.1892 -> 0.1776
year accuracy=0.9740 -> 0.3683
```

Raporlar:

```text
trdizin_model_comparison/comparison_test100/COMPARISON_REPORT.md
trdizin_model_comparison/comparison_test100/comparison_summary.json
trdizin_model_comparison/comparison_test100/document_deltas.csv
```

Training surumuyle uyumlu `0.9.1-SNAPSHOT` Docker imaji build edildikten sonra
ilk 20 test dokumaniyla smoke tekrarlandi:

```bash
PORT=8071 CONTAINER_NAME=grobid-trdizin-new-model-snapshot \
  RECREATE=1 ./start_grobid_new_model_docker.sh

GROBID_URL=http://127.0.0.1:8071 LIMIT=20 WORKERS=1 \
  RUN_ROOT=trdizin_model_comparison_snapshot_smoke \
  ./run_local_process_references_comparison.sh
```

Snapshot smoke sonucu:

```text
baseline good documents=20/20
candidate good documents=19/20
baseline reference match rate=0.9732
candidate reference match rate=0.9662
baseline date coverage=0.9820
candidate date coverage=0.4017
baseline year accuracy=0.9696
candidate year accuracy=0.3946
```

Author icinde kalan yili post-process ile date gibi sayan ek metrik:

```text
candidate repaired date coverage=0.4680
candidate repaired year accuracy=0.4600
date repaired from author=55 references
```

Raporlar:

```text
trdizin_model_comparison_snapshot_smoke_author_repair/comparison_test20/comparison_summary.json
trdizin_model_comparison_snapshot_smoke_author_repair/comparison_test20/document_deltas.csv
```

Yorum: Held-out CRF evaluation iyi gorunse de end-to-end `processReferences`
pilotunda mevcut `6118781` modeli, ozellikle `date/year` alaninda ciddi
geriliyor. Author-date post-process bazi kayitlari kurtariyor ama baseline'a
yaklastirmiyor; bu nedenle bu model temiz date/year duzeltmesinden onceki corpus
ile egitildigi icin final kabul edilmemeli.

## Clean-Date 6126604 Model Evaluation

`6118781` modelindeki ana hata, training corpus'ta yayin yilinin cok sayida
referansta `<author>` icinde kalmasiydi. Bu hata `clean_date_good10k` corpus ile
duzeltildi ve yeni Wapiti CRF egitimi `6126604` job'u olarak calistirildi.

Training ozeti:

```text
job_id=6126604
corpus=trdizin_full_reference_training_clean_date_good10k
train/dev/test split=9000/500/500 XML
max_iter=200
final token error=0.93%
final sequence error=9.61%
local model=remote_training_artifacts/6126604/model.clean-date.iter0200.6126604.wapiti
```

Same-image local test kosullari:

```text
image=grobid-local:0.9.1-snapshot-crf
endpoint=processReferences
consolidateCitations=0
includeRawCitations=1
test documents=first 100 IDs from held-out test split
baseline=stock/default model in the same 0.9.1-SNAPSHOT image
candidate=6126604 clean-date model mounted as citation/model.wapiti
```

Aligned `processReferences` karsilastirmasi:

| Metric | Stock/default | 6118781 old model | 6126604 clean-date | 6126604 vs stock |
|---|---:|---:|---:|---:|
| good documents | 100/100 | 97/100 | 100/100 | 0 |
| reference match rate | 0.9761 | 0.9463 | 0.9751 | -0.0010 |
| year accuracy | 0.9731 | 0.3593 | 0.9639 | -0.0092 |
| author coverage | 0.9794 | 0.9836 | 0.9784 | -0.0010 |
| article title coverage | 0.7476 | 0.7018 | 0.7062 | -0.0414 |
| journal title coverage | 0.7060 | 0.6794 | 0.6834 | -0.0226 |
| scope coverage | 0.7899 | 0.7895 | 0.7870 | -0.0029 |
| date coverage | 0.9881 | 0.3751 | 0.9727 | -0.0154 |
| DOI coverage | 0.1892 | 0.1776 | 0.1726 | -0.0166 |

Raw TEI inference karsilastirmasi:

| Metric | Stock/default | 6118781 old model | 6126604 clean-date |
|---|---:|---:|---:|
| produced references | 4187 | 4112 | 4174 |
| author coverage | 0.9690 | 0.9720 | 0.9713 |
| article title coverage | 0.7330 | 0.6773 | 0.6917 |
| journal title coverage | 0.6924 | 0.6605 | 0.6677 |
| scope coverage | 0.7743 | 0.7748 | 0.7731 |
| date coverage | 0.9759 | 0.3723 | 0.9626 |
| DOI coverage | 0.1863 | 0.1727 | 0.1699 |
| raw reference coverage | 1.0000 | 1.0000 | 1.0000 |

Stock/default modele gore durum tablosu:

| Alan | 6126604 durumu | Yorum | Sonraki aksiyon |
|---|---:|---|---|
| Reference satiri bulma | Cok yakin | Iki model de referans satirlarini neredeyse tam yakaliyor. Sorun satiri bulmak degil, satirin icindeki alanlari etiketlemek. | Segmentasyon tarafini simdilik bloklamadan alan etiketleme kalitesine odaklan. |
| Date/year | Stocktan biraz dusuk, 6118781'den cok iyi | Clean-date corpus asil yil hatasini buyuk olcude duzeltti; yine de stock modele tam yetismedi. | Date projection kurallarini pilot QA ile genislet; access/retrieval date ayrimini koru. |
| Author | Neredeyse esit | Author coverage farki cok kucuk. Clean-date duzeltmesi author alanini bozmus gorunmuyor. | Author-date ayrimi icin daha fazla edge case manuel kontrol et. |
| Article title | Stocktan dusuk | TR Dizin kaynakli projection title span'larini yeterince temiz/kararli uretmiyor olabilir. | Title baslangic/bitis kurallarini ayri QA metriğine bagla. |
| Journal title | Stocktan dusuk | Dergi adi, yayin bilgisi ve scope alanlari bazi referanslarda birbirine karisiyor. | Journal/scope ayrimi icin ornek bazli hata listesi cikar. |
| DOI | Stocktan dusuk | DOI zaten az gorulen bir alan; kucuk farklar coverage'a sert yansiyor. | DOI/URL regex projection kontrollerini ayri test et. |

Sonuc:

```text
6126604 date/year problemini buyuk olcude duzeltti.
Reference segmentation ve match rate stock modele cok yaklasti.
Ancak article title, journal title ve DOI coverage halen stock/default modelden dusuk.
Bu nedenle 6126604, 6118781'e gore net iyilesme olsa da genel deploy karari icin
stock modeli gecmis sayilmamali.
```

Raporlar:

```text
trdizin_model_comparison_snapshot_stock_vs_6126604/comparison_test100/comparison_summary.json
trdizin_model_comparison_snapshot_stock_vs_6126604/comparison_test100/raw_inference_coverage.json
trdizin_model_comparison_snapshot_stock_vs_6126604/comparison_test100/document_deltas.csv
```

Sonraki iyilestirme hedefi date degil; `article_title`, `journal_title` ve
`doi` projection kalitesidir. Full training'e tekrar girmeden once corpus QA
bu alanlari da gate olarak olcmelidir.

## Sik Hatalar

Yanlis klasorden grafik calistirma:

```text
can't open file '/Users/.../grobid-source/plot_wapiti_training_log.py'
```

Cozum:

```bash
cd /Users/isikgiray/Desktop/ULAKBİM/grobid
python3 plot_wapiti_training_log.py train_citation.<JOBID>.err --target-iteration 150
```

`tail -f`ten cikmak:

```text
Ctrl+C
```
