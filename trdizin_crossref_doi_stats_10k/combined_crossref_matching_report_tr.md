# 10k TR Dizin Referansı: Birleşik Crossref Eşleşme Raporu

Bu rapor 10.000 referanslık örnek üzerinde üç aşamalı Crossref eşleştirme sonucudur:

1. Referanstan DOI ayıkla ve Crossref `works/{doi}` ile kontrol et.
2. DOI var ama Crossref DOI sorgusunda bulunamadıysa başlık/yazar/yıl ile bibliographic fallback yap.
3. DOI hiç yoksa yerel TEI'den çıkarılabilen başlık/yazar/yıl bilgisini, yoksa temizlenmiş referans metnini kullanarak Crossref bibliographic search yap.

## Ana Sonuç

- Toplam referans: 10.000
- DOI içeren referans: 1.948
- DOI içermeyen referans: 8.052
- DOI-only Crossref eşleşmesi: 1.855 (%18,55)
- DOI-404 bibliographic fallback güçlü eşleşme: 60
- DOI'siz bibliographic fallback güçlü eşleşme: 3.692
- Nihai strict Crossref eşleşmesi: 5.607 (%56,07)
- Nihai broad Crossref eşleşmesi: 5.826 (%58,26)
- Search error: 0

## Aşama Detayı

### DOI ile Doğrudan Arama

- DOI bulunan referans: 1.948
- Crossref'te DOI ile bulunan: 1.855
- Crossref'te DOI ile bulunamayan: 93

### DOI Var Ama DOI Sorgusu 404 Dönenler

- Kontrol edilen: 93
- Güçlü bibliographic eşleşme: 60
- Olası eşleşme: 3
- Eşleşme yok: 30
- Hata: 0

Bu grup çoğunlukla bozuk/kırpılmış DOI içeriyor. Örneğin `10.1038/s41415.020.2406-9` Crossref'te `10.1038/s41415-020-2406-9` olarak bulundu.

### DOI'siz Referanslar

- Kontrol edilen DOI'siz referans: 8.052
- Güçlü bibliographic eşleşme: 3.692
- Olası eşleşme: 216
- Eşleşme yok: 4.144
- Hata: 0

DOI'siz referanslarda güçlü kurtarma oranı %45,85; olası eşleşmeler de dahil edilirse %48,53.

## Yorum

Başlangıçta sadece DOI ile Crossref bulunma oranı %18,55 idi. Bibliographic fallback sonrası güvenli kabul edilebilecek strict oran %56,07'ye çıktı. Olası eşleşmeler manuel kontrolle kabul edilirse oran %58,26'ya çıkıyor.

En büyük kazanım DOI'siz referanslardan geldi. Bu, TR Dizin kaynakça metinlerinde DOI'nin sıkça yazılmadığını, ancak aynı yayınların önemli bir kısmının Crossref'te başlık/yazar/yıl ile bulunabildiğini gösteriyor.
