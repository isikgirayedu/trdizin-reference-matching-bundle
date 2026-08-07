# DOI Yok Referanslar: Kısa Rapor

10.000 TR Dizin referansı içinde 8.052 referansta parse edilebilir DOI bulunmadı. Bu sonuç, ilgili çalışmaların kesinlikle DOI'si olmadığı anlamına gelmez; bu örneklem için ölçülen şey, TR Dizin referans metninde DOI'nin açık ve ayıklanabilir biçimde bulunup bulunmadığıdır.

## Genel Sonuç

- Örneklenen referans: 10.000
- DOI bulunan referans: 1.948 (%19,48)
- DOI bulunmayan referans: 8.052 (%80,52)
- DOI'si olan referanslarda Crossref'te bulunan: 1.855 (%95,23)
- DOI'si olan referanslarda Crossref'te bulunamayan: 93 (%4,77)
- Crossref sorgu hatası: 0

## DOI Neden Yok Görünüyor?

1. Referans metnine DOI hiç yazılmamış.
   DOI'siz kayıtların büyük kısmı standart kaynakça metni olarak geliyor; yazar, yıl, başlık, dergi, cilt/sayı/sayfa var ama DOI alanı yok. Özellikle 1.967 referans dergi makalesi gibi görünüyor fakat DOI içermiyor.

2. Kaynak türü DOI kullanımına uygun olmayabilir.
   917 kitap/kitap bölümü, 244 tez, 193 kurum/rapor/mevzuat türü kaynak ve 61 konferans bildirisi tespit edildi. Bu türlerde DOI ya hiç atanmaz ya da kaynakçada düzenli verilmez.

3. Eski yayınlarda DOI kapsaması düşük.
   845 referans 2000 öncesi yayınlara veya eski tarihli kaynaklara işaret ediyor. DOI altyapısı eski yayınlarda her zaman geriye dönük tamamlanmış değil.

4. DOI yerine URL verilmiş.
   497 referansta URL veya erişim bilgisi var. Bu kayıtlar DOI yerine web adresiyle cite edilmiş.

5. Veri kalitesi/OCR/format sorunları var.
   455 DOI'siz kayıtta `doi`, `doi.org` veya `CrossRef` ifadesi geçiyor; ancak düzgün DOI çıkarılamıyor. Tipik sorunlar: DOI içinde boşluk, eksik DOI suffix'i, sadece `[CrossRef]` yazılması, OCR kaynaklı karakter/parçalama hataları.

## Kısa Yorum

Crossref tarafındaki kapsama DOI verilen referanslarda yüksek: DOI'si ayıklanabilen referansların %95,23'ü Crossref'te bulundu. Bu yüzden ana darboğaz Crossref araması değil, TR Dizin referans metinlerinde DOI'nin eksik, bozuk veya hiç verilmemiş olması.
