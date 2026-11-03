# Canlı tahta, sesli cevap ve dört ek özellik: tasarım

- **Tarih:** 2026-11-02
- **Durum:** onaylandı (kullanıcı: "önerdiğin gibi yap") ve uygulanıyor.

## Kullanıcının kararları

| Soru | Karar |
|---|---|
| Tahta nerede | Ekranın ortasında, biraz sağda duran bir kart |
| Ses | Varsayılan açık. Kutuda bir sustur düğmesi var. |
| Ne zaman çizer | Rabik karar verir; kullanıcı "çiz", "göster" ya da "3D" derse her zaman çizer |
| Ek özellikler | "Hey Rabik", Bugün öğrendiklerim, odak dürtmeleri, toplantı öncesi brifing |

## 1. Canlı tahta

**Ne yapar.** Plan, süreç, karşılaştırma, rakam ya da "nasıl çalışır" türü bir soruda Rabik cevabı sesli anlatır ve bu sırada bir kartta adım adım yazar ve çizer.

- Örnek: "Şirketim için pazarlama planı" sorusunda Rabik "Birincisi…" derken tahtada "1. Müşteriyi tanı" kutusu elle çiziliyormuş gibi belirir ve oka bağlanır.
- Fiziksel bir şey anlatıyorsa (motor, molekül, gezegen) tahta 3D olur:
  - parçalar konuşmayla birlikte büyür;
  - sürükleyince döner;
  - bir parçaya tıklanınca Rabik o parçayı anlatır.

**Model ne yazar.** Cevap `[board <düzen>: <başlık>]` ile başlar. Ardından satır satır küçük bir dil gelir:

```
[board flow: Acme için pazarlama planı]
say Birincisi, kime sattığını netleştir.
item Müşteriyi tanı | kim alıyor, neden, nerede arıyor
say Sonra kazanabileceğin iki kanal seç.
item İki kanal seç | SEO · LinkedIn
[/board]
```

- **Düzenler:** `flow`, `mind`, `compare`, `timeline`, `chart`, `cycle`, `3d`.
- **İşaretler:** `say`, `item`, `column`, `bar`, `note`, `check`, `circle`, `formula`, `part` (3D).
- `[board+]` açık tahtaya ekleme yapar; takip sorularında kullanılır.

Bu biçimin seçilme nedenleri:

- Satır satır olduğu için akış hâlinde ayrıştırılabilir. İlk satır gelir gelmez çizim başlar.
- Haiku bile hatasız yazabilir.
- Model kod çalıştırmaz. Her satır doğrulanır, bilinmeyen satır atılır.

**Akış.**

1. `brain/board.py` modelin metin parçalarını izler ve her tam satırı doğrular.
2. Her satırı `◫ {json}` olayı olarak uygulamaya yollar.
3. Kutuya `… <anlatım>` gider ve anlatılan cümleler altyazı gibi akar.
4. Son cevap (`✓`) anlatımın düz metnidir. Hafıza ve geçmiş bunu saklar.

**Ses ile eşleme.**

- Her `say` satırı `Speaker` kuyruğuna tek parça olarak girer.
- `Speaker`'a cümle başına bir başlama geri çağrısı eklenir. Bu geri çağrı cümlenin süresini de verir.
- Bir cümle başlayınca ondan sonra gelen işaretler o cümlenin süresine yayılarak çizilir. Bu, HeyClicky'deki adım adım tempoyla aynıdır.
- Ses kapalıysa her adım okuma hızında ilerler: kelime başına yaklaşık 0,33 sn, en az 1,2 sn.
- Kullanıcı söze girerse ses durur ve kalan çizimler hızla tamamlanır.

**Görünüm** (`ui/board.html`, tek dosya, ağ yok, kütüphane yok):

- Krem kâğıt üzerine el çizimi:
  - SVG çizgiler iki kez hafif titreyerek çizilir ve `stroke-dashoffset` ile kalemden çıkıyormuş gibi açılır;
  - yazı Mac'te hazır bulunan el yazısı yazı tipleriyle (Noteworthy ya da Chalkboard SE) harf harf belirir.
- İçerik büyüdükçe görüş alanı yumuşakça genişler.
- 3D için kendi küçük WebGL çizicimiz var:
  - kutu, küre, silindir, koni ve simit;
  - Lambert ışık, sürükleyerek döndürme, tekerle yakınlaştırma;
  - parçaya tıklayınca renk-kimliğiyle seçim ve parça adlarının etiketleri.
- Kartın üstünde başlık, "Resim olarak kaydet" (Downloads klasörüne PNG) ve ✕ bulunur. Kart başlıktan sürüklenir.

**Ne zaman.**

- Sistem isteminde tek kısa satır bulunur.
- Tam kullanım yalnızca istek tahtaya uygun sözcükler içerdiğinde (İngilizce ve Türkçe) isteğe eklenir: plan, explain, how, compare, diagram, çiz, göster, nasıl, anlat ve benzerleri.
- Bu, zamanlamada kullandığımız düzenle aynıdır ve 10.000 karakterlik istem bütçesini korur.

## 2. Sesli cevap

- `speak` artık varsayılan olarak açık.
- Mevcut kurulumlar bir kez açılır (`speakDefaulted` işareti). Sonra kullanıcı kapatırsa kapalı kalır.
- Kutuda bir hoparlör düğmesi var. Tek tıkla sesi kapatır ya da açar; konuşma sürüyorsa hemen susturur.

## 3. "Hey Rabik"

- **Ayar:** Settings → Voice → "Hey Rabik". Varsayılan kapalı, çünkü mikrofon sürekli açık kalır ve turuncu nokta görünür.
- **Dinleme:** Rabik boştayken mikrofonu cihaz üstü konuşma tanıma ile dinler. Ses dışarı çıkmaz, hiçbir şey kaydedilmez.
- **Tetikleme:** "hey rabik" (ve "hey rabbit", "hey robik" gibi yakın duyuşlar) duyunca kısayola basılmış gibi dinlemeye başlar. Sessizlik gelince durur.
- **Ne zaman durur:** toplantıda, Rabik konuşurken, duraklatılmışken ve ekran kilitliyken dinlemez.

## 4. Bugün öğrendiklerim

- Akşam özeti, Rabik'in o gün öğrendiği "About you" gerçeklerini listeler.
- Her satırda "Doğru" ve "Unut" düğmeleri var. "Unut" gerçeği siler. Mevcut `--profile` komutları kullanılır.

## 5. Odak dürtmeleri

- Açık bir hedef varken kullanıcı 5 dakikadan uzun süre dikkat dağıtan bir uygulamada ya da sitede kalırsa nazik bir bildirim gelir.
  - Uygulama ve site örnekleri: YouTube, X, Instagram, TikTok, Reddit, Netflix, Twitch, Facebook.
  - Örnek bildirim: "YouTube'da 6 dk oldu. Bugünkü hedefin: beta'yı çıkarmak. Dönelim mi?"
- **Sınırlar:**
  - günde en fazla 3 bildirim;
  - iki bildirim arasında en az 45 dakika;
  - toplantıda, ekran paylaşırken ve duraklatılmışken bildirim yok.
- Hedef yoksa hiç çalışmaz.
- **Ayar:** "Focus nudges", varsayılan açık.

## 6. Toplantı öncesi brifing

- Takvimde başka katılımcıları olan bir toplantıdan 5 dakika önce Rabik kısa bir brifing hazırlar. Kaynakları:
  - People notları;
  - o kişilerle geçmiş toplantıların özetleri;
  - açık işler.
- Brifing Haiku ile 3–5 madde olarak yazılır ve bildirim olarak gelir. Bildirime tıklanınca brifing kutuda açılır ve okunur.
- **Ayar:** "Meeting briefs", varsayılan açık.
- Bir etkinlik için brifing yalnızca bir kez hazırlanır.

## Test

**Python:**

- tahta dilinin ayrıştırılması ve doğrulanması (geçersiz satır, sınırlar, `[board+]`);
- akış hâlinde olay üretimi;
- son cevaptan anlatım metninin çıkarılması;
- istem bütçesi ve yardımın hangi isteklerde eklendiği;
- odak kuralı (süre, sınırlar, hedef yoksa sessiz);
- brifing girdileri;
- öğrenilenler listesi.

**Sayfa (gerçek WebKit):**

- `board.html` olayları alıp işaret sayısını, oynatma sırasını ve 3D parça sayısını doğru gösterir;
- JavaScript sözdizimi denetimi.

**Swift:**

- `Speaker` başlama geri çağrısının kaynağı;
- `Board` panelinin derlenmesi;
- yeni ayarların varsayılanları.

**Uçtan uca:** sürüm derlemesi `/Applications` klasörüne kurulur ve gerçek bir soruyla bilgisayar kullanımı üzerinden denenir.
