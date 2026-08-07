# Crossref SimpleTextQuery Raporu

Bu çalışma, Crossref'in web aracı olan SimpleTextQuery ile 10.000 TR Dizin referansı üzerinde yapıldı:

`https://apps.crossref.org/SimpleTextQuery`

Referanslar 1.000 ve 500'lük batchler halinde gönderildi. 1.000'lik batchlerden biri timeout verdiği için kalan bölüm 500'lük batchlere bölündü.

## SimpleTextQuery Sonucu

- Toplam referans: 10.000
- SimpleTextQuery DOI buldu: 5.673 (%56,73)
- Kaynakta DOI olan referans: 1.948
- Kaynakta DOI olup STQ'nin bulduğu: 1.899 (%97,48)
- Kaynakta DOI olmayan referans: 8.052
- Kaynakta DOI yokken STQ'nin bulduğu: 3.774 (%46,87)

## Önceki Pipeline ile Karşılaştırma

Önceki pipeline: `works/{doi}` + DOI-404 bibliographic fallback + DOI'siz bibliographic fallback.

- Önceki strict eşleşme: 5.607 (%56,07)
- Önceki broad eşleşme: 5.826 (%58,26)
- SimpleTextQuery eşleşme: 5.673 (%56,73)

Strict karşılaştırma:

- Hem STQ hem strict pipeline buldu: 5.333
- Sadece STQ buldu: 340
- Sadece strict pipeline buldu: 274

Broad karşılaştırma:

- Hem STQ hem broad pipeline buldu: 5.447
- Sadece STQ buldu: 226
- Sadece broad pipeline buldu: 379

## Not

STQ sonucu önceki strict pipeline'dan biraz daha yüksek, broad pipeline'dan biraz daha düşük çıktı. İki yöntemin bulduğu kayıtlar birebir aynı değil; STQ 226 kaydı broad pipeline'ın bulmadığı şekilde buldu, broad pipeline ise STQ'nin bulmadığı 379 kaydı buldu.

İki yöntemin aynı referans için farklı DOI döndürdüğü 95 kayıt var. Bunlar manuel kontrol için ayrıca çıkarıldı.
