const totalReferences = 10000;

const summary = {
  total: totalReferences,
  withDoi: 1948,
  withoutDoi: 8052,
  searchErrors: 1,
};

const experiments = [
  {
    id: "doi",
    label: "Deney 1",
    title: "Sadece DOI",
    found: 1855,
    rate: 18.55,
    description:
      "Referanstaki DOI alinir ve Crossref works DOI endpoint'i ile kontrol edilir. DOI olmayan referanslar bu deneyde aranmaz.",
    note: "DOI'li 1.948 referansin 1.855 tanesi Crossref'te bulundu.",
    color: "#276ef1",
    components: [
      { label: "Crossref DOI endpoint", value: 1855, color: "#276ef1" },
    ],
  },
  {
    id: "strict",
    label: "Deney 2",
    title: "Strict",
    found: 5607,
    rate: 56.07,
    description:
      "DOI endpoint sonucu korunur; DOI ile bulunamayan ve DOI'siz referanslarda bibliographic arama yapilir. Sadece guclu eslesmeler sayilir.",
    note: "Possible eslesmeler haric tutuldu; strong esik kullanildi.",
    color: "#159a8c",
    components: [
      { label: "DOI endpoint", value: 1855, color: "#276ef1" },
      { label: "DOI 404 strong", value: 60, color: "#d99216" },
      { label: "DOI yok strong", value: 3692, color: "#159a8c" },
    ],
  },
  {
    id: "stq",
    label: "Deney 3",
    title: "SimpleTextQuery",
    found: 5673,
    rate: 56.73,
    description:
      "Crossref SimpleTextQuery web formuna serbest metin referanslar gonderildi. Bu, en son calistirdigimiz deney.",
    note: "DOI'li referanslarda 1.899, DOI'siz referanslarda 3.774 eslesme buldu.",
    color: "#d85b48",
    components: [
      { label: "DOI'li ref bulundu", value: 1899, color: "#276ef1" },
      { label: "DOI'siz ref bulundu", value: 3774, color: "#d85b48" },
    ],
  },
  {
    id: "openalex",
    label: "Deney 4",
    title: "OpenAlex fallback",
    found: 6071,
    rate: 60.71,
    description:
      "Tum Crossref denemelerinin birlesiminde bulunmayan 3.948 referans OpenAlex API'ye hedef olarak verildi.",
    note:
      "Anonim OpenAlex kredisi nedeniyle partial: 125 hedef kontrol edildi, 19 strong eslesme bulundu, 3.823 hedef henuz kontrol edilmedi.",
    color: "#d99216",
    components: [
      { label: "Crossref union", value: 6052, color: "#159a8c" },
      { label: "OpenAlex strong", value: 19, color: "#d99216" },
    ],
  },
  {
    id: "datacite",
    label: "Deney 5",
    title: "DataCite REST API",
    found: 6071,
    rate: 60.71,
    description:
      "OpenAlex sonrasi kalan 3.929 referans DataCite REST API ile kontrol edildi. DOI varsa /dois/{doi}, digerlerinde /dois?query aramasi kullanildi.",
    note:
      "Tamamlandi: 3.929 hedef islendi; 0 strong, 0 possible, 3.925 no_match, 4 sorgulanamaz kayit. Toplam oran degismedi.",
    color: "#4f7f52",
    components: [
      { label: "Onceki baz", value: 6071, color: "#d99216" },
      { label: "DataCite yeni", value: 0, color: "#4f7f52" },
    ],
  },
  {
    id: "openalex-key",
    label: "Deney 6",
    title: "OpenAlex API key resume",
    found: 6072,
    rate: 60.72,
    description:
      "Deney 4'te API limiti yuzunden bakilamayan OpenAlex hedefleri API key ile yeniden calistirildi.",
    note:
      "Partial: 3.948 hedefin 1.041'i kontrol edildi; 20 strong eslesme bulundu. Deney 4'e gore +1 yeni strong geldi, 2.907 hedef API butcesi nedeniyle kaldi.",
    color: "#0f766e",
    components: [
      { label: "Crossref union", value: 6052, color: "#159a8c" },
      { label: "OpenAlex strong", value: 20, color: "#0f766e" },
    ],
  },
  {
    id: "dergipark",
    label: "Deney 7",
    title: "DergiPark OAI-PMH",
    found: 6099,
    rate: 60.99,
    description:
      "Deney 6 sonrasi kalan referanslarda DergiPark URL'lerinden article id veya journal slug yakalanip OAI-PMH GetRecord/ListRecords ile denenir.",
    note:
      "Dogrudan DergiPark TCP timeout verdigi icin OAI cevabi Jina Reader fallback ile cekildi. 27 GetRecord hedefinin tamami strong eslesti; 15 article-file URL OAI identifier vermedigi icin disarida kaldi.",
    color: "#8a5a16",
    components: [
      { label: "Onceki baz", value: 6072, color: "#0f766e" },
      { label: "DergiPark strong", value: 27, color: "#8a5a16" },
    ],
  },
  {
    id: "crossref-cleanup",
    label: "Deney 8",
    title: "Crossref cleanup",
    found: 6101,
    rate: 61.01,
    description:
      "Deney 7 sonrasi kalan kayitlarda gizli DOI, temizlenmis referans ve title/journal/year query varyantlari Crossref'te yeniden denendi.",
    note:
      "False-positive riskini dusurmek icin sadece yil + yazar + yuksek title coverage saglayan guvenli eslesmeler sayildi. 849 sorgulanabilir hedeften 2 strong geldi.",
    color: "#5b7cfa",
    components: [
      { label: "Onceki baz", value: 6099, color: "#8a5a16" },
      { label: "Cleanup strong", value: 2, color: "#5b7cfa" },
    ],
  },
  {
    id: "europepmc",
    label: "Deney 9",
    title: "Europe PMC",
    found: 6123,
    rate: 61.23,
    description:
      "Deney 8 sonrasi kalan biomedical/article-like referanslar Europe PMC REST API'de PMID veya title/query ile arandi.",
    note:
      "81 biomedical hedef denendi; 22 strong eslesme geldi. Bunlarin 3 tanesinde DOI alanı da dondu.",
    color: "#b45309",
    components: [
      { label: "Onceki baz", value: 6101, color: "#5b7cfa" },
      { label: "Europe PMC strong", value: 22, color: "#b45309" },
    ],
  },
  {
    id: "dergipark-file",
    label: "Deney 10",
    title: "DergiPark article-file",
    found: 6123,
    rate: 61.23,
    description:
      "Kalan DergiPark download/article-file URL'lerinde file id, OAI article id olabilir mi diye Jina/OAI GetRecord ile probelandi.",
    note:
      "15 hedef denendi; metadata donse bile title/year/author skoru gecmeden sayilmadi. Yeni eslesme gelmedi: 14 no_match, 1 request error.",
    color: "#6f6f46",
    components: [
      { label: "Onceki baz", value: 6123, color: "#b45309" },
      { label: "Article-file yeni", value: 0, color: "#6f6f46" },
    ],
  },
  {
    id: "journal-like-parser",
    label: "Deney 11",
    title: "Journal-like parser",
    found: 6124,
    rate: 61.24,
    description:
      "Deney 10 sonrasi kalan 740 journal-like referans gelismis parser ile title/journal/year/author alanlarina ayrildi; structured Crossref retry ve DergiPark lokal OAI index fuzzy match calisti.",
    note:
      "551 baslik+dergi parse edildi, 550 structured Crossref query denendi, 17 DergiPark setinden 1.697 metadata kaydi indexlendi. Guvenli esiklerle 1 strong DergiPark eslesmesi geldi.",
    color: "#0e7490",
    components: [
      { label: "Onceki baz", value: 6123, color: "#6f6f46" },
      { label: "DergiPark index strong", value: 1, color: "#0e7490" },
    ],
  },
  {
    id: "trdizin-target",
    label: "Deney 12",
    title: "TR Dizin targetPublication",
    found: 6363,
    rate: 63.63,
    description:
      "Deney 11 sonrasi kalan referanslarda TR Dizin'in kendi targetPublication alanı kullanildi; hedef yayin metadata'si publicationById API ile cekildi.",
    note:
      "239 yeni strict TR Dizin ic eslesme geldi. Bunlarin 16'sinda hedef metadata DOI vardi; 13 DOI Crossref works endpoint'inde dogrulandi.",
    color: "#166534",
    components: [
      { label: "Deney 11 baz", value: 6124, color: "#0e7490" },
      { label: "Crossref dogrulu hedef DOI", value: 13, color: "#276ef1" },
      { label: "TR Dizin ID resolved", value: 226, color: "#166534" },
    ],
  },
  {
    id: "trdizin-title",
    label: "Deney 13",
    title: "TR Dizin title search",
    found: 6367,
    rate: 63.67,
    description:
      "Deney 12 sonrasi kalan referanslarda parser ile cikarilan baslik/yil bilgisi TR Dizin defaultSearch/publication API'de arandi.",
    note:
      "3.637 kalan icinde 551 title-search hedefi uretildi. Siki title/yil/journal/author skoru ile 4 yeni strong TR Dizin eslesme geldi.",
    color: "#7f1d1d",
    components: [
      { label: "Deney 12 baz", value: 6363, color: "#166534" },
      { label: "TR Dizin title strong", value: 4, color: "#7f1d1d" },
    ],
  },
  {
    id: "hidden-doi",
    label: "Deney 14",
    title: "Hidden DOI cleanup",
    found: 6367,
    rate: 63.67,
    description:
      "Deney 13 sonrasi kalan kayitlarda metin icine gomulmus DOI benzeri ifadeler tekrar normalize edilip Crossref DOI endpoint'inde kontrol edildi.",
    note:
      "11 hidden DOI hedefi ve 11 unique DOI adayi denendi. Hicbiri guvenli Crossref strong eslesmeye donmedi; toplam oran degismedi.",
    color: "#16a34a",
    components: [
      { label: "Deney 13 baz", value: 6367, color: "#7f1d1d" },
      { label: "Hidden DOI strong", value: 0, color: "#16a34a" },
    ],
  },
  {
    id: "dergipark-file-v2",
    label: "Deney 15",
    title: "DergiPark article-file v2",
    found: 6367,
    rate: 63.67,
    description:
      "Kalan DergiPark article-file URL'leri tekrar article id olasiligiyle probelandi ve metadata donerse strict title/year/author esigiyle filtrelendi.",
    note:
      "11 hedef denendi; 0 strong, 0 possible, 11 no_match. Article-file id'leri OAI article id olarak guvenli cozum vermedi.",
    color: "#6f6f46",
    components: [
      { label: "Deney 14 baz", value: 6367, color: "#16a34a" },
      { label: "Article-file strong", value: 0, color: "#6f6f46" },
    ],
  },
  {
    id: "isbn-book",
    label: "Deney 16",
    title: "ISBN / book resolver",
    found: 6367,
    rate: 63.67,
    description:
      "Kitap/bolum gibi kalan kayitlarda gecerliligi kontrol edilen ISBN adaylari OpenCitations Meta ISBN endpoint'i ile arandi.",
    note:
      "9 hedefte 11 unique ISBN adayi denendi. Title/year skoru strong esigi gecmedigi icin yeni otomatik eslesme sayilmadi.",
    color: "#a85522",
    components: [
      { label: "Deney 15 baz", value: 6367, color: "#6f6f46" },
      { label: "ISBN strong", value: 0, color: "#a85522" },
    ],
  },
  {
    id: "doi-eligible",
    label: "Deney 17",
    title: "DOI-eligible denominator",
    found: 6367,
    denominator: 8038,
    missingLabel: "DOI-eligible kalan",
    rate: 79.21,
    description:
      "Bu deney yeni eslesme eklemez; kitap, tez, web, rapor/mevzuat ve konferans gibi DOI beklenmesi zayif turleri toplam paydadan ayirarak operasyonel DOI-eligible oranini hesaplar.",
    note:
      "3.633 kalan kaydin 1.962'si DOI-unlikely kategoriye dustu. Payda 8.038 olarak alindiginda mevcut 6.367 cozumun orani 79,21%.",
    color: "#9333ea",
    components: [
      { label: "Auto resolved", value: 6367, color: "#9333ea" },
    ],
  },
  {
    id: "pubmed",
    label: "Deney 18",
    title: "PubMed Citation Matcher",
    found: 6367,
    rate: 63.67,
    description:
      "Biomedical gorunen 50 kalan referans PubMed Citation Matcher ile PMID adayina baglandi; adaylar strict title/year kosullariyla otomatik sayima alindi.",
    note:
      "15 PMID possible aday geldi ama 0 strong sayildi. DOI'li strong cikmadigi icin genel toplam Deney 13 ile ayni kaldi.",
    color: "#0f766e",
    components: [
      { label: "Deney 17 baz", value: 6367, color: "#9333ea" },
      { label: "PubMed strong", value: 0, color: "#0f766e" },
    ],
  },
  {
    id: "grobid-reparse",
    label: "Deney 19",
    title: "GROBID re-parse",
    found: 6410,
    rate: 64.1,
    description:
      "Deney 18 sonrasi kalan referanslar ham GROBID processReferences TEI alanlariyla yeniden parse edildi; DOI direct, Crossref bibliographic, TR Dizin title search ve OpenAlex retry calisti.",
    note:
      "1.302 retry hedefinden 43 strong geldi. OpenAlex tarafinda 955/1.254 sorgu cache'lendi, 299 sorgu socket takilmasi nedeniyle bu kosuda atlandi; strong sayim strict tutuldu.",
    color: "#2563eb",
    components: [
      { label: "Deney 18 baz", value: 6367, color: "#0f766e" },
      { label: "GROBID DOI + Crossref", value: 24, color: "#276ef1" },
      { label: "GROBID Crossref biblio", value: 6, color: "#5b7cfa" },
      { label: "GROBID TR Dizin", value: 8, color: "#166534" },
      { label: "GROBID OpenAlex", value: 5, color: "#d99216" },
    ],
  },
  {
    id: "fuzzy-matching",
    label: "Deney 20",
    title: "Fuzzy Matching (Şükran)",
    found: 6415,
    rate: 64.15,
    description:
      "Deney 19 sonrasi kalan 3.590 referans uzerinde harf hatalarini, Turkce karakter bozukluklarini ve format farklarini tolere eden Gestalt + Damerau-Levenshtein + Jaro-Winkler hibrit benzerlik modeli ve Multi-API (Crossref, OpenAlex, Google Books) altyapisi eklendi.",
    note:
      "gelistirme-sukran dalinda Jaro-Winkler ve Damerau-Levenshtein hibrit modeliyle 3.590 kalan referans tarandi. 5 yeni strong DOI eslesmesi kazanildi (%64.10 -> %64.15).",
    color: "#e11d48",
    components: [
      { label: "Deney 19 baz", value: 6410, color: "#2563eb" },
      { label: "Deney 20 Hibrit (Jaro-Winkler + DL)", value: 5, color: "#e11d48" },
    ],
  },
  {
    id: "broad",
    label: "Ek Deney",
    title: "Broad",
    found: 5826,
    rate: 58.26,
    description:
      "Strict pipeline sonucuna possible eslesmeler de eklenir. Daha cok yakalar ama hatali eslesme riski strict'e gore daha yuksektir.",
    note: "Strict 5.607 eslesmeye 219 possible eslesme eklendi.",
    color: "#7a5ccf",
    components: [
      { label: "Strict eslesme", value: 5607, color: "#159a8c" },
      { label: "Possible ek", value: 219, color: "#7a5ccf" },
    ],
  },
];

const remainingAfterExperiment19 = {
  found: 6410,
  foundRate: 64.1,
  remaining: 3590,
  remainingRate: 35.9,
  doiUnlikely: 1947,
  doiUnlikelyRateOfRemaining: 54.23,
};

const remainingCategories = [
  {
    key: "other",
    label: "Diger / zayif parse",
    count: 1071,
    remainingRate: 29.83,
    totalRate: 10.71,
    color: "#64748b",
    note: "Belirgin kategoriye dusmeyen veya parse kalitesi zayif kalan referans.",
  },
  {
    key: "book_or_chapter",
    label: "Kitap / kitap bolumu",
    count: 949,
    remainingRate: 26.43,
    totalRate: 9.49,
    color: "#7c3aed",
    note: "Kitap, yayinevi veya kitap bolumu sinyali tasiyor.",
  },
  {
    key: "journal_like_left",
    label: "Journal-like kalan",
    count: 551,
    remainingRate: 15.35,
    totalRate: 5.51,
    color: "#2563eb",
    note: "Cilt/sayi/sayfa formati var ama guvenli API eslesmesi gelmedi.",
  },
  {
    key: "url_web",
    label: "Web / haber / video",
    count: 473,
    remainingRate: 13.18,
    totalRate: 4.73,
    color: "#dc2626",
    note: "Web sayfasi, haber, video, sosyal medya veya erisim URL'si agirlikli.",
  },
  {
    key: "thesis",
    label: "Tez",
    count: 291,
    remainingRate: 8.11,
    totalRate: 2.91,
    color: "#0891b2",
    note: "Tez/dissertation sinyali tasiyor; Crossref DOI denominator'i icin zayif aday.",
  },
  {
    key: "report_policy_legal",
    label: "Rapor / mevzuat / hukuk",
    count: 182,
    remainingRate: 5.07,
    totalRate: 1.82,
    color: "#b45309",
    note: "Rapor, resmi belge, mevzuat veya hukuk kaynagi sinyali tasiyor.",
  },
  {
    key: "conference",
    label: "Konferans / bildiri",
    count: 52,
    remainingRate: 1.45,
    totalRate: 0.52,
    color: "#4f46e5",
    note: "Konferans, kongre, sempozyum veya bildiri sinyali tasiyor.",
  },
  {
    key: "dergipark_file",
    label: "DergiPark article-file",
    count: 10,
    remainingRate: 0.28,
    totalRate: 0.1,
    color: "#6f6f46",
    note: "Download/article-file URL var; OAI article id kesin degil.",
  },
  {
    key: "hidden_doi",
    label: "Gizli DOI",
    count: 11,
    remainingRate: 0.31,
    totalRate: 0.11,
    color: "#16a34a",
    note: "Metinde DOI benzeri ifade var ama onceki DOI pipeline'ina temiz yakalanmamis.",
  },
];

const categoryExamples = {
  other: [
    {
      sampleIndex: "6993",
      publicationId: "1217592",
      referenceId: "19048550",
      referenceOrder: "1",
      text: "Akgobek, O. and Cakir, F. (2009), Veri madenciliginde bir uzman sistem tasarimi, Akademik Bilisim Konferansi Bildirileri 09-XI, 11-13 Subat Harran Universitesi, Sanliurfa, 801-806.",
    },
    {
      sampleIndex: "7354",
      publicationId: "1174773",
      referenceId: "16650240",
      referenceOrder: "13",
      text: "Chavali, K. - Mohan Raj, P. - Ahmed, R. (2021), \"Does Financial Behavior Influence Financial Well-Being?\", The Journal of Asian Finance, Economics and Business, 8(2), pp. 273-280.",
    },
    {
      sampleIndex: "360",
      publicationId: "1275970",
      referenceId: "21378640",
      referenceOrder: "6",
      text: "[6] Shabat, A., & Zakharov, V. (1972). Exact theory of two-dimensional self-focusing and one-dimensional self-modulation of waves in nonlinear media. Soviet Physics JETP, 34(1), 62.",
    },
  ],
  book_or_chapter: [
    {
      sampleIndex: "6665",
      publicationId: "1168369",
      referenceId: "16374631",
      referenceOrder: "1",
      text: "1. Camsari T, Saglam F. Kronik Bobrek Yetmezligi. In: Erol C, Suleymanlar, ed. Ic Hastaliklari Nefroloji. Birinci Baski. Ankara: MN Medikal&Nobel Yayinevi, 2011; 85-97. [CrossRef]",
    },
    {
      sampleIndex: "6856",
      publicationId: "1287077",
      referenceId: "21808817",
      referenceOrder: "43",
      text: "Yenturk, N., Kurtaran, Y., Ne Mutlu, G. (2007). Gencler Hakkinda, Genclik icin, Genclerle Turkiye'de Genclik Calismasi ve Politikalari, Istanbul Bilgi Universitesi Yayinlari. 3-22.",
    },
    {
      sampleIndex: "2759",
      publicationId: "1293587",
      referenceId: "23053619",
      referenceOrder: "46",
      text: "Wallerstein, I. (2011). Dunya sistemleri analizi bir giris. Bgst Yayinlari - 43, 2. Basim, Hazirlayan: Taylan Dogan, Omer F. Kurhan, Ceviren: Ender Abadoglu, Nuri Ersoy, Istanbul.",
    },
  ],
  journal_like_left: [
    {
      sampleIndex: "1197",
      publicationId: "1292790",
      referenceId: "22048751",
      referenceOrder: "48",
      text: "Qureshia, M. H. ve Abbas, K. (2019). Performance Analysis of Islamic and Traditional Banks of Pakistan. International Journal of Economics Management and Accounting. 27(1): 83-104.",
    },
    {
      sampleIndex: "2033",
      publicationId: "1326405",
      referenceId: "23650609",
      referenceOrder: "26",
      text: "Karagoz, Y., & Agbektas, A. (2016). Yapisal esitlik modellemesi ile yasam memnuniyeti modelinin gelistirilmesi. Bartin Universitesi Iktisadi Idari Bilimler Dergisi, 7(13), 274-290.",
    },
    {
      sampleIndex: "3671",
      publicationId: "1272701",
      referenceId: "21057223",
      referenceOrder: "22",
      text: "22. Mansoub N. Performance, carcass quality, blood parameters and immune system of broilers fed diets supplemented with oregano oil (Origanum sp.). Ann Biol Res. 2011;2(6):652-656.",
    },
  ],
  url_web: [
    {
      sampleIndex: "1769",
      publicationId: "1312037",
      referenceId: "23435383",
      referenceOrder: "45",
      text: "\"Adik Tersanesi\", https://www.adik.com.tr/products/lst, erisim 28.02.2024. \"Air Force\", Global Fire, http://www.globalfirepower,com/aircraft-total-transport.php, erisim 27.02.2024.",
    },
    {
      sampleIndex: "6498",
      publicationId: "1266852",
      referenceId: "21272457",
      referenceOrder: "25",
      text: "25. Uluslararasi Hemsirelik Konseyi (ICN). (2020). Erisim adresi: https://www.icn.ch/news/icn-calls-data-healthcare-worker-infection-rates-and-deaths. (Erisim tarihi: 13.09.2023).",
    },
    {
      sampleIndex: "5536",
      publicationId: "1314060",
      referenceId: "23008988",
      referenceOrder: "140",
      text: "\"There's a Chance to Open New Era in Caucasus\" - Armenian Foreign Minister at Antalya Forum, JAM News, 14 Nisan 2025, https://jam-news.net/armenian-fm-on-antalya-diplomacy-forum/.",
    },
  ],
  thesis: [
    {
      sampleIndex: "980",
      publicationId: "1369846",
      referenceId: "25424875",
      referenceOrder: "4",
      text: "Bayburtoglu, S. (2005). 1980 sonrasi Turk sinemasi ve Yavuz Turgul. (Yayimlanmamis Yuksek Lisans Tezi). Mimar Sinan Guzel Sanatlar Universitesi Sosyal Bilimler Enstitusu, Istanbul.",
    },
    {
      sampleIndex: "2364",
      publicationId: "1336651",
      referenceId: "24087856",
      referenceOrder: "14",
      text: "Cakar, D. (2016). Kulturel mirasi koruma baglaminda \"yavas sehir\" (cittaslow) hareketi: Turkiye ornegi. Yuksek Lisans Tezi. Dokuz Eylul Universitesi. Fen Bilimleri Enstitusu. Izmir.",
    },
    {
      sampleIndex: "6154",
      publicationId: "1351467",
      referenceId: "24665913",
      referenceOrder: "2",
      text: "Ay, B. (1996). Kiyi Alanlari Ile Ilgili Mevzuat, Kiyi Kentlerinin Sorunlari ve Kiyi Planlamasina Isik Tutacak Ilkelerin Saptanmasi (Doctoral dissertation, Fen Bilimleri Enstitusu).",
    },
  ],
  report_policy_legal: [
    {
      sampleIndex: "1236",
      publicationId: "1162808",
      referenceId: "16519015",
      referenceOrder: "86",
      text: "Ozel Guvenlik Hizmetlerine Dair Kanun (2004, 14 Haziran). Resmi Gazete (Sayi: 8843). Erisim adresi: https://www.mevzuat.gov.tr/MevzuatMetin/1.5.5188.pdf, Erisim tarihi: 15.04.2022.",
    },
    {
      sampleIndex: "4658",
      publicationId: "1328699",
      referenceId: "23752997",
      referenceOrder: "92",
      text: "Icisleri Bakanligi. (2023). Ankara'da yilbasi denetimleri KGYS merkezi'nden takip ediliyor. https://www.icisleri.gov.tr/ankarada-yilbasi-denetimleri-kgys-merkezinden-takip-ediliyor",
    },
    {
      sampleIndex: "4350",
      publicationId: "1182017",
      referenceId: "17124816",
      referenceOrder: "21",
      text: "Hoca Sadettin Efendi, Tacu't-Tevarih 3 Fatih Sultan Mehmed ve II. Bayezid Donemleri, (Haz. I Parmaksizoglu), Istanbul: Kultur Bakanligi Yayinlari/301 Bilim Dizisi/1, Istanbul 1979.",
    },
  ],
  conference: [
    {
      sampleIndex: "238",
      publicationId: "1280839",
      referenceId: "21466856",
      referenceOrder: "42",
      text: "Roy, N. ve Debnath, A. (2011). \"Impact of migration on economic development: A study of some selected state\", International Conference on Social Science and Humanity, 5, 198-202.",
    },
    {
      sampleIndex: "3357",
      publicationId: "1298683",
      referenceId: "23254005",
      referenceOrder: "179",
      text: "Riese, J. (2005). Salutogenesis in social systems: Self, identity, and robustness of the organization. Proceedings of the European Academy of Management Conference, 1-32, Munich.",
    },
    {
      sampleIndex: "9883",
      publicationId: "1259494",
      referenceId: "20488574",
      referenceOrder: "84",
      text: "Turoglu, H. (2005, September 29-30). Trabzon-Sarp arasi, Karadeniz sahil yolu insaatinin jeomorfolojik etkileri (Conference session). Ulusal Cografya Kongresi, Istanbul, Turkey.",
    },
  ],
  dergipark_file: [
    {
      sampleIndex: "641",
      publicationId: "1182531",
      referenceId: "17001915",
      referenceOrder: "69",
      text: "Yesilyaprak, B. (2011). Duygusal zeka ve egitim acisindan dogurgulari. Kuram ve Uygulamada Egitim Yonetimi, 25(25), 139-146. https://dergipark.org.tr/en/download/article-file/108511",
    },
    {
      sampleIndex: "2337",
      publicationId: "1373862",
      referenceId: "25571186",
      referenceOrder: "61",
      text: "Yalcin, E. Semih, \"Dahiliye Vekili Nazim Bey'in Istifasi Meselesi.\" Ataturk Arastirma Merkezi Dergisi XI, 32 (1995): 405-416. https://dergipark.org.tr/tr/download/article-file/1172083",
    },
    {
      sampleIndex: "4133",
      publicationId: "1356322",
      referenceId: "24864948",
      referenceOrder: "8",
      text: "Cetin-Erus, Z. (2020). Turkiye sinemasinda uyarlamalara genel bir bakis. Turkiye Arastirmalari Literatur Dergisi, 18(36), 583-592. https://dergipark.org.tr/tr/download/article-file/1291023",
    },
  ],
  hidden_doi: [
    {
      sampleIndex: "3695",
      publicationId: "1328696",
      referenceId: "23752717",
      referenceOrder: "3",
      text: "Ardan M, Rahman F.F. & Geroda, G.B. (2020). Theinfluence of physicaldistancetostudentanxiety on Covid-19, Indonesia. J CritRev. 7(17), 1126-32. DOI: 10.31838/jcr.07.17.141.",
    },
    {
      sampleIndex: "2530",
      publicationId: "1333057",
      referenceId: "24222718",
      referenceOrder: "23",
      text: "Ghafoori, N., & Diaz-Loya, I. (2012). Shrinkage Cracking and Durability Characteristics of Alkali-Activated Slag Concrete. Materials Journal, 109(2), 209-217. https://doi.org/10.14359/51684395.",
    },
    {
      sampleIndex: "3750",
      publicationId: "1285408",
      referenceId: "21723305",
      referenceOrder: "27",
      text: "Ismail, R. ve Jajri, I. (2012). Gender wage differentials and discrimination in Malaysian labour market. World Applied Sciences Journal, 19(5), 719-728. DOI: 10.5829/idosi.wasj.2012.19.05.1114",
    },
  ],
};

const remainingReasons = [
  {
    label: "TR Dizin ic link/title ile cozuldu",
    value: 243,
    rate: 6.27,
    text: "Deney 12 ve 13, Deney 10 sonrasi kalanlardan 243 referansi guvenli TR Dizin eslesmesi olarak cozdu.",
  },
  {
    label: "DOI beklenmesi zayif turler",
    value: 1962,
    rate: 54.0,
    text: "Kitap, tez, web, rapor/mevzuat ve konferans kayitlari DOI/Crossref pipeline'ini dogal olarak dusuruyor.",
  },
  {
    label: "Deney 14-18 ek strong",
    value: 0,
    rate: 0.0,
    text: "Hidden DOI, DergiPark article-file, ISBN/OpenCitations ve PubMed denemeleri strong eslesme uretmedi; Deney 17 sadece payda metrigidir.",
  },
  {
    label: "Deney 19 GROBID ek strong",
    value: 43,
    rate: 1.18,
    text: "GROBID re-parse ile DOI/Crossref/TR Dizin/OpenAlex retry sonucunda 43 yeni strong eslesme eklendi.",
  },
  {
    label: "Journal-like ama guvenli eslesmeyen",
    value: 551,
    rate: 15.35,
    text: "Makale gibi gorunuyorlar; fakat Crossref, STQ, OpenAlex, Europe PMC, DergiPark ve TR Dizin search ile guvenli match vermedi.",
  },
  {
    label: "Zayif parse / belirsiz kaynak",
    value: 1071,
    rate: 29.83,
    text: "Baslik, dergi veya yil ayrimi net olmadigi icin API adaylari false-positive riskini artiriyor.",
  },
];

const formatNumber = new Intl.NumberFormat("tr-TR");
const formatRate = (value) => `${value.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;

function setText(id, value) {
  document.getElementById(id).textContent = value;
}

function createCategoryExampleButton(category) {
  const button = document.createElement("button");
  button.className = "category-example-button";
  button.type = "button";
  button.dataset.category = category.key;
  button.textContent = "Ornek goster";
  button.addEventListener("click", () => renderCategoryExamples(category.key));
  return button;
}

function renderSummary() {
  setText("totalReferences", formatNumber.format(summary.total));
  setText("doiReferences", formatNumber.format(summary.withDoi));
  setText("noDoiReferences", formatNumber.format(summary.withoutDoi));
  setText("searchErrors", formatNumber.format(summary.searchErrors));
}

function renderExperiment(experimentId) {
  const experiment = experiments.find((item) => item.id === experimentId) || experiments[0];
  const denominator = experiment.denominator || totalReferences;
  const missing = denominator - experiment.found;
  const missingLabel = experiment.missingLabel || "Bulunamayan";

  document.querySelectorAll(".experiment-button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.experiment === experiment.id);
  });

  setText("experimentLabel", experiment.label);
  setText("experimentTitle", experiment.title);
  setText("experimentRate", formatRate(experiment.rate));
  setText("experimentDescription", experiment.description);
  setText("experimentNote", experiment.note);
  setText("matchCount", `${formatNumber.format(experiment.found)} / ${formatNumber.format(denominator)}`);
  setText("foundText", `Bulunan: ${formatNumber.format(experiment.found)}`);
  setText("missingText", `${missingLabel}: ${formatNumber.format(missing)}`);
  setText("componentTotal", formatNumber.format(experiment.found));

  const matchBar = document.getElementById("matchBar");
  matchBar.style.width = `${experiment.rate}%`;
  matchBar.style.background = experiment.color;

  const components = document.getElementById("componentBars");
  components.replaceChildren(
    ...experiment.components.map((component) => {
      const row = document.createElement("div");
      row.className = "component-item";

      const label = document.createElement("span");
      label.className = "component-label";
      label.textContent = component.label;

      const track = document.createElement("div");
      track.className = "component-track";

      const fill = document.createElement("div");
      fill.className = "component-fill";
      fill.style.width = `${Math.min((component.value / denominator) * 100, 100)}%`;
      fill.style.background = component.color;
      track.append(fill);

      const value = document.createElement("span");
      value.className = "component-value";
      value.textContent = formatNumber.format(component.value);

      row.append(label, track, value);
      return row;
    })
  );
}

function renderComparisonBars() {
  const container = document.getElementById("comparisonBars");

  container.replaceChildren(
    ...experiments.map((experiment) => {
      const row = document.createElement("div");
      row.className = "comparison-row";

      const name = document.createElement("span");
      name.className = "comparison-name";
      name.textContent = experiment.title;

      const track = document.createElement("div");
      track.className = "comparison-track";

      const fill = document.createElement("div");
      fill.className = "comparison-fill";
      fill.style.width = `${experiment.rate}%`;
      fill.style.background = experiment.color;
      track.append(fill);

      const value = document.createElement("span");
      value.className = "comparison-value";
      value.textContent = experiment.denominator
        ? `${formatNumber.format(experiment.found)} / ${formatNumber.format(experiment.denominator)} (${formatRate(experiment.rate)})`
        : `${formatNumber.format(experiment.found)} (${formatRate(experiment.rate)})`;

      row.append(name, track, value);
      return row;
    })
  );
}

function renderExperimentTable() {
  const tbody = document.getElementById("experimentTable");

  tbody.replaceChildren(
    ...experiments.map((experiment) => {
      const row = document.createElement("tr");

      const name = document.createElement("td");
      name.textContent = `${experiment.label}: ${experiment.title}`;

      const found = document.createElement("td");
      found.textContent = `${formatNumber.format(experiment.found)} / ${formatNumber.format(experiment.denominator || totalReferences)}`;

      const rate = document.createElement("td");
      rate.textContent = formatRate(experiment.rate);

      const note = document.createElement("td");
      note.textContent = experiment.note;

      row.append(name, found, rate, note);
      return row;
    })
  );
}

function renderRemainingStats() {
  setText("remainingFound", formatNumber.format(remainingAfterExperiment19.found));
  setText("remainingFoundRate", formatRate(remainingAfterExperiment19.foundRate));
  setText("remainingCount", formatNumber.format(remainingAfterExperiment19.remaining));
  setText("remainingRate", formatRate(remainingAfterExperiment19.remainingRate));
  setText("doiUnlikelyCount", formatNumber.format(remainingAfterExperiment19.doiUnlikely));
  setText("doiUnlikelyRate", formatRate(remainingAfterExperiment19.doiUnlikelyRateOfRemaining));

  renderRemainingTypeChart();
  renderRemainingReasons();

  const bars = document.getElementById("remainingCategoryBars");
  bars.replaceChildren(
    ...remainingCategories.map((category) => {
      const row = document.createElement("div");
      row.className = "remaining-row";

      const label = document.createElement("span");
      label.className = "remaining-name";
      label.textContent = category.label;

      const track = document.createElement("div");
      track.className = "comparison-track";

      const fill = document.createElement("div");
      fill.className = "comparison-fill";
      fill.style.width = `${category.remainingRate}%`;
      fill.style.background = category.color;
      track.append(fill);

	      const value = document.createElement("span");
	      value.className = "comparison-value";
	      value.textContent = `${formatNumber.format(category.count)} (${formatRate(category.remainingRate)})`;
	
	      row.append(label, track, value, createCategoryExampleButton(category));
	      return row;
	    })
	  );

  const tbody = document.getElementById("remainingCategoryTable");
  tbody.replaceChildren(
    ...remainingCategories.map((category) => {
      const row = document.createElement("tr");

      const name = document.createElement("td");
      name.textContent = category.label;

      const count = document.createElement("td");
      count.textContent = formatNumber.format(category.count);

      const remainingRate = document.createElement("td");
      remainingRate.textContent = formatRate(category.remainingRate);

      const totalRate = document.createElement("td");
      totalRate.textContent = formatRate(category.totalRate);

      const note = document.createElement("td");
      note.textContent = category.note;

      row.append(name, count, remainingRate, totalRate, note);
      return row;
    })
  );
}

function renderRemainingTypeChart() {
  const donut = document.getElementById("remainingTypeDonut");
  const donutCount = document.getElementById("remainingTypeDonutCount");
  if (donutCount) {
    donutCount.textContent = formatNumber.format(remainingAfterExperiment19.remaining);
  }
  let cursor = 0;
  const gradientParts = remainingCategories.map((category) => {
    const start = cursor;
    const end = cursor + category.remainingRate;
    cursor = end;
    return `${category.color} ${start}% ${end}%`;
  });
  donut.style.background = `conic-gradient(${gradientParts.join(", ")})`;

  const legend = document.getElementById("remainingTypeLegend");
  legend.replaceChildren(
    ...remainingCategories.map((category) => {
      const item = document.createElement("div");
      item.className = "legend-item";

      const swatch = document.createElement("span");
      swatch.className = "legend-swatch";
      swatch.style.background = category.color;

      const label = document.createElement("span");
      label.className = "legend-label";
      label.textContent = category.label;

	      const value = document.createElement("strong");
	      value.textContent = `${formatNumber.format(category.count)} (${formatRate(category.remainingRate)})`;
	
	      item.append(swatch, label, value, createCategoryExampleButton(category));
	      return item;
	    })
	  );
}

function renderCategoryExamples(categoryKey) {
  const panel = document.getElementById("categoryExamplePanel");
  if (!panel) {
    return;
  }
  const category = remainingCategories.find((item) => item.key === categoryKey) || remainingCategories[0];
  const examples = categoryExamples[category.key] || [];

  document.querySelectorAll(".category-example-button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.category === category.key);
  });

  const heading = document.createElement("div");
  heading.className = "panel-title-row";

  const titleWrap = document.createElement("div");
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = "Kategori ornekleri";

  const title = document.createElement("h3");
  title.textContent = category.label;
  titleWrap.append(eyebrow, title);

  const count = document.createElement("span");
  count.className = "example-count";
  count.textContent = `${formatNumber.format(category.count)} kayit`;
  heading.append(titleWrap, count);

  const list = document.createElement("div");
  list.className = "category-example-list";
  list.replaceChildren(
    ...examples.map((example) => {
      const item = document.createElement("article");
      item.className = "category-example-item";

      const meta = document.createElement("div");
      meta.className = "example-meta";
      meta.textContent = `sample ${example.sampleIndex} | publication ${example.publicationId} | ref ${example.referenceId} | sira ${example.referenceOrder}`;

      const text = document.createElement("p");
      text.textContent = example.text;

      item.append(meta, text);
      return item;
    })
  );

  panel.replaceChildren(heading, list);
}

function renderRemainingReasons() {
  const container = document.getElementById("remainingReasonList");
  container.replaceChildren(
    ...remainingReasons.map((reason) => {
      const item = document.createElement("div");
      item.className = "reason-item";

      const top = document.createElement("div");
      top.className = "reason-top";

      const label = document.createElement("span");
      label.textContent = reason.label;

      const value = document.createElement("strong");
      value.textContent = `${formatNumber.format(reason.value)} (${formatRate(reason.rate)})`;

      const text = document.createElement("p");
      text.textContent = reason.text;

      top.append(label, value);
      item.append(top, text);
      return item;
    })
  );
}

document.querySelectorAll(".experiment-button").forEach((button) => {
  button.addEventListener("click", () => renderExperiment(button.dataset.experiment));
});

renderSummary();
renderExperiment("doi");
renderComparisonBars();
renderExperimentTable();
renderRemainingStats();
renderCategoryExamples(remainingCategories[0].key);
