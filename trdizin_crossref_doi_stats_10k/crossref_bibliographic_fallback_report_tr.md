# Crossref Bibliographic Fallback Raporu

Bu çalışma, 10.000 referanslık örnekte DOI ile Crossref'te bulunamayan kayıtlar için yapıldı. Kapsam DOI'si hiç olmayan 8.052 referans değil; DOI ayıklanan ama `works/{doi}` sorgusunda Crossref 404 dönen 93 referanstır.

## Yöntem

Her referans için DOI/URL parçaları temizlendi ve kalan bibliyografik metin Crossref `query.bibliographic` aramasıyla sorgulandı. Dönen adaylar başlık kapsaması, yazar soyadı örtüşmesi ve yıl uyumuna göre değerlendirildi.

- `strong`: güvenli eşleşme sayılabilecek kayıt
- `possible`: elle kontrol edilmesi gereken olası eşleşme
- `no_match`: yeterli bibliyografik kanıt yok

## Fallback Sonucu

- Kontrol edilen DOI-404 referans: 93
- Güçlü bibliyografik eşleşme: 60
- Olası bibliyografik eşleşme: 3
- Eşleşme yok: 30
- Crossref arama hatası: 0

## Güncellenmiş İstatistik

Başlangıçta 10.000 referansta 1.948 DOI ayıklanmıştı. Bunların 1.855'i DOI ile Crossref'te bulunmuş, 93'ü bulunamamıştı.

Bibliyografik fallback sonrası:

- Strict sonuç: 1.915 Crossref eşleşmesi
- Strict oran: tüm referanslarda %19,15; DOI'li referanslarda %98,31
- Broad sonuç: 1.918 Crossref eşleşmesi
- Broad oran: tüm referanslarda %19,18; DOI'li referanslarda %98,46
- DOI-404 kayıt kurtarma oranı, strong only: %64,52
- DOI-404 kayıt kurtarma oranı, strong + possible: %67,74

## Yorum

DOI ile bulunamayan 93 kaydın büyük kısmı aslında Crossref'te var görünüyor; problem çoğunlukla referanstaki DOI'nin eksik, parçalanmış veya yanlış karakterle yazılmış olması. Örnekler:

- `10.1038/s41415.020.2406-9` yerine Crossref'te `10.1038/s41415-020-2406-9`
- `10.1007/s00266-024-03961-` yerine Crossref'te `10.1007/s00266-024-03961-y`
- `10.1186/s40643-021-00416-2` yerine Crossref'te `10.1186/s40643-021-00416-z`
- `10.1016/j` gibi kesilmiş DOI'lerin Crossref'te tam DOI karşılığı bulunabiliyor

Bu yüzden DOI verilen referanslarda Crossref kapsaması ham DOI sorgusuyla %95,23 iken, bibliyografik fallback ile güvenli hesapta %98,31'e çıkıyor.
