# Rabik test planı (gerçek kullanım)

Release build'i (`dist/Rabik-<sürüm>.dmg`) bu Mac'te uçtan uca denemek için. Her madde: ne yapılır → ne olmalı.
Bir şey bozulursa ne yaptığını ve ne gördüğünü yaz; ayrıntı `~/.config/rabik/log.jsonl`'da (her istek, adımları ve komutları).

Bu build hakkında:
- Developer ID ile imzalı, **notarize edilmemiş**: bu Mac'te açılır, başka bir Mac'e indirilen kopyayı Gatekeeper engeller.
- Release build'de açılışta başlama (login item) yok: Rabik'i `/Applications`'tan ya da Spotlight'tan elle aç.
- Safe mode varsayılan olarak açık. Ana istekler artık Claude Code sandbox'ında (AUDIT §9).

## 1. Kurulum ve ilk açılış
- [ ] DMG'yi aç, Rabik'i Applications'a sürükle, aç → kurulum penceresi açılır, Rabik simgesi menü çubuğunda görünür.
- [ ] Kurulum Claude planını bulur (Claude Code kurulu ve giriş yapılmış) → "Change provider" gerekmeden ilerler.
- [ ] İzinler tek tek sorulur: Mikrofon, Konuşma tanıma, Erişilebilirlik, Ekran kaydı, Otomasyon (Apple Events) → her biri verildikten sonra kurulum devam eder.
- [ ] Kurulum bitince Safe mode notu görünür ("deleting, sending or buying asks you first").

## 2. Kısayol ve kutu
- [ ] ⌃⌥Space basılı tut, "Spotify'ı aç" de, bırak → Spotify açılır; AI kullanılmaz (anlık komut, kart yok).
- [ ] "Terminal'i sola al" → Terminal penceresi sola yerleşir.
- [ ] Kutuda yazarak sor (mikrofonsuz) → aynı şekilde çalışır.
- [ ] Cevap gelirken kısayola bas → durur. Dinlerken Esc → iptal, hiçbir şey çalışmaz.
- [ ] Bir cevaba tıkla → kopyalanır. Boş kutuda ↑ → son istek geri gelir.

## 3. AI istekleri (Claude)
- [ ] "Ekranda ne var, tek cümleyle" → ekrana bakıp cevap verir.
- [ ] "Masaüstümdeki en son PDF'i bul ve aç" → dosyayı bulup açar.
- [ ] "Bu sayfayı üç maddede özetle" (Safari/Chrome'da bir makale açıkken) → sayfayı okuyup özetler.
- [ ] "Night Shift'i nerede açarım?" → ekranda doğru yeri gösteren bir halka/çizim çıkar.
- [ ] Aynı yeni isteği ikinci kez söyle → ikinci sefer çok daha hızlı (öğrenilmiş kısayol, AI yok).
- [ ] "Remember my favorite color is blue", sonra "what's my favorite color?" → hatırlar.
- [ ] "Open my browser" → varsayılan tarayıcı açılır (System Settings → Desktop & Dock → Default web browser), adı "Browser" ile biten başka bir uygulama değil.
- [ ] "Okay, so every time I say work mode, open Notes and put it on the left" → yapar; sonra "work mode" deyince AI olmadan, anında tekrarlar.

## 4. Safe mode ve sandbox (bu sürümün asıl yeniliği)
- [ ] "Spotify'ı aç", "Chrome'u sağ ekrana al", "github.com'u aç" → **kart çıkmadan** çalışır.
- [ ] Masaüstüne birkaç deneme PDF'i koy, "Masaüstündeki PDF'leri Raporlar diye bir klasöre taşı" de →
      bir onay kartı çıkar ("Delete something?" ya da "Run outside the safe folder?"); onaylayınca dosyalar gerçekten taşınır.
      Klasör oluşturma ayrı bir adım olursa ikinci bir kart çıkabilir (beklenen).
- [ ] Aynı istekte kartta **Don't Allow** de → hiçbir dosya taşınmaz ve cevap "yapılmadı" der.
- [ ] Cevaplarda hiçbir zaman "/sandbox" geçmez.
- [ ] "Bu metni panoya kopyala: merhaba" → çalışıyor mu? (`pbcopy` sandbox'ta takılırsa kart çıkar; hangisi olduğunu not et.)
- [ ] "Merhaba de" (sesli) ya da "ekran görüntüsü al ve masaüstüne kaydet" → çalışıyor mu, kart çıkıyor mu? Not et.
- [ ] İlk cevabın süresi: aynı soruyu birkaç kez sor; belirgin bir yavaşlama var mı? Not et.

## 5. Dikte
- [ ] Bir metin alanında (Notes) fn tuşunu basılı tut, konuş, bırak → yazı imlecin olduğu yere düşer.
- [ ] fn'e iki kez bas → kilitli dikte (turuncu halka); bir kez daha bas → metin eklenir.

## 6. Ekranı gösterme ve çizim
- [ ] Kutudaki işaretçi düğmesi (Point at your screen) → bir şeyi daire içine al, "bu ne?" diye sor → işaretlediğin yer hakkında cevap verir.
- [ ] "Pisagor teoremini açıkla ve ekranıma çiz" → adım adım çizim ve yanda bir açıklama kartı çıkar; Esc ya da kartı kapatmak çizimi kaldırır.

## 7. Arka plan ajanları
- [ ] "Bana 30 doların altında USB-C hub bul" → köşede bir ajan çipi çıkar, sen çalışmaya devam edersin.
- [ ] Çipin üstüne gel → canlı adımlar ve küçük ekran görünür.
- [ ] "Hub ajanına HDMI'ı da kontrol etmesini söyle" → çalışan ajan yönlendirilir, yenisi açılmaz.
- [ ] Ajan bir dosya yazmak ya da komut çalıştırmak isterse onay kartı çıkar ("Allow this task action?").
- [ ] Bitince bir sonuç kartı çıkar; ajanın tarayıcı penceresi kapanır, senin sekmelerine dokunulmaz.

## 8. Takvim, izleme, rutinler
- [ ] "Yarın saat 3'e diş hekimi ekle" → hemen eklenir. "Diş hekimini 4'e al" → eski/yeni saatli bir kart çıkar, onayla taşınır.
- [ ] "Bu sayfa 'shipped' yazınca haber ver" → izleme kurulur; "stop watching" ile durur.
- [ ] "Her gün 9'da takvimimi özetle" → rutin kaydedilir; Settings → General → Scheduled routines'da görünür ve oradan silinir.

## 8b. Akşam özeti ve Hatırlatıcılar
- [ ] Gün içinde birkaç istek yap, sonra "summarize my day" (ya da "günümü özetle") de → kutuda özet kartı açılır: başlık, Bugün, Kararlar, Yapılacaklar, Yarın.
- [ ] Bir yapılacak satırına tıkla → işaretlenir, düğme "Add 1 to Reminders" olur. Bas → ilk seferde Hatırlatıcılar izni sorulur; izin verince madde Hatırlatıcılar'ın varsayılan listesine düşer, kartta ✓ Added olarak kalır.
- [ ] Aynı maddeyi tekrar eklemeye çalış → eklenemez (düğme yok ya da pasif).
- [ ] Settings → General → Daily recap'te saati bir iki dakika sonrasına al → o saatte "Your day with Rabik" bildirimi gelir (ilk seferde bildirim izni sorulur); tıklayınca kart kutuda açılır.
- [ ] Bildirim geldikten sonra Mac'i uyutup uyandır ya da Rabik'i yeniden aç → aynı gün ikinci bildirim gelmez.
- [ ] Settings'te "Reminders list" seçicisinde, ilk eklemeden sonra kendi listelerin görünür; başka bir liste seçip ekle → madde o listeye düşer.
- [ ] Bir toplantıdan sonra panelin altındaki "Action items" listesinden bir madde seçip ekle; Settings → Meetings'te o toplantıyı aç → aynı madde "Added to Reminders" görünür.
- [ ] Daily recap'i kapat → o saatte bildirim gelmez.

## 9. Toplantı (isteğe bağlı)
- [ ] Settings → Meetings → Meeting Copilot'u aç, demo'yu dene → panel açılır, sürüklenir, küçülür.
- [ ] Demo bitince "See all meetings" → kayıt arşivde görünür.
- [ ] Settings → Meetings → Language'ı Turkish yap, Türkçe konuşulan bir görüşme (ya da video) aç → satırlar Türkçe yazılır. Automatic'te Mac'in dili kullanılır.
- [ ] "Translate the call"u aç → karşı tarafın her satırının altında Mac'in dilinde çevirisi çıkar. Dil paketi yoksa bir kez "Translation Languages" uyarısı gelir.
- [ ] Takvimde tek kişiyle olan bir görüşmede satırlar o kişinin adıyla görünür. Kalabalık bir görüşmede birkaç dakika sonra, adı geçen kişilerin satırlarında italik isimler belirir; emin olunmayanlar "Them" kalır.
- [ ] Görüşme bitince "Share recap…" → Paylaş menüsü açılır; Notes'a gönderince başlık, özet ve maddeler gelir, transkript gelmez. Settings → Meetings'teki "Share…" de aynısını yapar.
- [ ] "Remind me before calls"u aç → linkli bir takvim görüşmesinden yaklaşık iki dakika önce küçük bir kart çıkar. Kapalıyken çıkmaz.

## 9b. Ses, hafıza, kişiler, hedefler, MCP
- [ ] Settings → General → "Read answers aloud"u aç, uzun bir soru sor → cevap akarken ilk cümleler okunmaya başlar. Voice'tan Premium/Enhanced bir ses seç (yoksa ipucu, Spoken Content'ten indirmeyi söyler). Türkçe bir cevap Türkçe sesle okunur.
- [ ] Rabik konuşurken konuşmaya başla → yaklaşık yarım saniyede susar (hoparlörden de denenmeli; kendi sesiyle susmamalı). "Stop when I talk" kapalıyken susmaz.
- [ ] "Dünkü toplantıda ne konuştuk?" → cevabın altında toplantı çipi çıkar; tıklayınca Settings → Meetings'te o toplantı açılır.
- [ ] Settings → Memory → Activity history'yi aç, birkaç dakika bir Figma/Safari sayfasında çalış → "az önce baktığım sayfayı aç" çalışır ve kaynak çipi çıkar. Gizli pencere ve şifre yöneticisi kaydedilmez; "Clear…" hepsini siler.
- [ ] Settings → People'da toplantılardaki kişiler görünür; birine tıklayınca toplantıları ve bilinenler çıkar; "Hide from People" listeden çıkarır. "Sam'le en son ne zaman konuştum?" kişi çipiyle cevaplanır.
- [ ] "Hedefim: beta'yı cuma çıkarmak" de → Settings → General → Goals'ta görünür; akşam özetinde günün katkısı varsa "Goals" satırı çıkar; "beta hedefini tamamladım" işaretler.
- [ ] Notion'u (veya Slack'i) aç; bağlayıcısı bağlı değilse kutuda bir kez öneri kartı çıkar. Not now bir hafta, Don't ask again kalıcı susturur. Toplantıdayken çıkmaz.
- [ ] Settings → Account & Access → "Add to Claude Code" → düğme "Added" olur; Claude Code'da `/mcp` listesinde rabik görünür ve "Rabik'te hedeflerim neler?" çalışır. "Copy for Claude Desktop" yapılandırmayı kopyalar.
- [ ] "Add to ChatGPT" → düğme "Added" olur; ChatGPT Mac uygulamasını yeniden başlat, Settings → MCP servers'ta rabik görünür ve "Rabik'te hedeflerim neler?" çalışır.

## 9c. Zamanlanmış görevler ve izleyiciler
- [ ] "Bugün saat 20:00'de Discord'a gir, Ali'ye 'geliyorum' yaz" de → "Run this later without asking?" kartı çıkar; onayla. Settings → General → Scheduled routines'te "Once on … at 8:00 PM · runs without asking" görünür. 20:00'de ajan sormadan yapar ve bildirim gelir; görev listeden düşer.
- [ ] "Her pazartesi ve perşembe 9'da takvimimi özetle" → "Mondays and Thursdays at 9:00 AM" olarak listelenir.
- [ ] Mac'i bir tek seferlik görevin saatinde uykuda bırak → varsayılan: yapılmaz, "Missed: …" bildirimi gelir. Settings'te "Run it up to 2 hours late" seçince geç de yapılır.
- [ ] "ChatGPT izin isterse onayla" de → "Click this whenever it appears?" kartı; onayla. ChatGPT bir izin istediğinde Rabik "Allow/Approve"a kendisi basar, dakikada en fazla bir bildirim gelir. Settings → General → Watches'ta sayaç artar; Stop ya da "izlemeyi durdur" kapatır.

## 9d. Canlı tahta, ses ve yeni yardımcılar
- [ ] "Küçük bir kahve dükkanım var, pazarlama planım nasıl olmalı?" → ekranın ortasının biraz sağında krem bir kart açılır; Rabik konuşurken her adım kutusu, okları ve notları o cümleyle birlikte elle çiziliyormuş gibi belirir. Kutuda anlatım yazı olarak akar.
- [ ] "Araba motoru nasıl çalışır, 3D göster" → parçalar konuşmayla büyüyen bir 3D model; sürükleyince döner, tekerlek yakınlaştırır, bir parçaya tıklayınca "… ne işe yarar?" sorusu gider ve aynı tahtaya eklenir ya da cevaplanır.
- [ ] "Kiralamak mı satın almak mı?" → iki sütunlu karşılaştırma; "Q1 40, Q2 55 gelir grafiği çiz" → çubuk grafik.
- [ ] Tahta çizerken konuş ya da kısayola bas → ses susar, kalan çizim hemen tamamlanır. ⤓ Downloads'a PNG kaydeder ("Saved to Downloads"), ✕ ya da Esc kapatır.
- [ ] Kutudaki hoparlör düğmesi: tıklayınca sessize alır (çarpı görünür), cevaplar okunmaz; tahta okuma hızında çizilir. Tekrar tıklayınca açar. İlk açılışta ses varsayılan olarak açık.
- [ ] Settings → General → Voice → "Hey Rabik"i aç (turuncu mikrofon noktası görünür) → "Hey Rabik" de → başlangıç sesi, dinleme başlar; sustuğunda soru gider. Discord/Zoom aramasındayken de duyar. Rabik konuşurken, toplantı notu alırken ve ekran kilitliyken dinlemez. Kapatınca nokta kaybolur.
- [ ] Ayrı mikrofon + ayrı hoparlör (USB mikrofon, monitör hoparlörü) ile canlı tahta sorusu sor → Mac donmaz, Activity Monitor'da coreaudiod %30'un altında kalır; 3D tahta 20 sn sonra dönmeyi bırakır ve WebKit %0'a iner.
- [ ] Bir hedef ekle, 5 dakikadan uzun YouTube'da kal → "6 min on YouTube. Your goal: … Back to it?" bildirimi; günde en fazla 3, aralarında 45 dk. Hedef yokken gelmez.
- [ ] Takvime 6 dk sonra, daha önce toplantı yaptığın biriyle bir toplantı koy → ~5 dk kala "Before “…” · in 5 min" bildirimi; tıklayınca brifing kutuda açılır ve okunur. Tanımadığın biriyle olan toplantıda gelmez.
- [ ] Rabik'e kendinle ilgili bir şey öğret ("kahvemi yulaf sütlü içerim") → akşam özetinde "Learned about you" altında görünür; Keep ✓ işaretler, Forget About you'dan siler.

## 10. Settings ve modlar
- [ ] Spotlight'tan "Rabik" → Settings açılır; açık/koyu görünüme uyar.
- [ ] Kutu varsayılan olarak ekranın üst ortasında açılır.
- [ ] Settings → General → Box position'da başka bir yere tıkla → kutu bir anlığına orada görünür; kısayolla açınca da orada açılır. Alt konumlarda kutu yukarı doğru büyür.
- [ ] "Kutuyu sağ alta al" de → ayar değişir.
- [ ] Menü çubuğunda Rabik'in yüzü görünür; açık ve koyu menü çubuğunda okunur, Rabik duraklatılınca soluklaşır.
- [ ] Safe mode notu: "Risky actions need approval. Commands write only to a scratch folder."
- [ ] Safe mode'u kapat (Full access): kutuda "Full access" etiketi çıkar; etikete tıklayınca Safe mode geri açılır.
- [ ] Full access'te dördüncü bölümdeki taşıma isteği kart çıkmadan çalışır (`rm` yine engellidir, dosyalar çöpe gider).
- [ ] Intelligence → Cheapest / Balanced / Most capable arasında geçiş → istekler çalışmaya devam eder.
- [ ] Menü çubuğu → Report Feedback… → bir GitHub issue taslağı açılır (gönderme).

## 11. Kaldırma
- [ ] Menü çubuğundan Quit, `Rabik.app`'i sil, istersen `~/.config/rabik`'i de sil (ayarlar ve geçmiş).
