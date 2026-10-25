# Doğal ses, sözü kesme, kaynaklı cevaplar, etkinlik geçmişi, kişiler, hedefler, bağlayıcı önerisi ve MCP — tasarım

Tarih: 2026-10-25 · Durum: onaylandı, uygulanıyor · Esin: Omi ve HeyClicky karşılaştırma tablosundaki 10, 11, 12, 13, 15, 16, 17, 18 numaralı maddeler

## Amaç

Rabik'i hem konuşan bir asistan hem de Mac'teki "ikinci hafıza" olarak güçlendirmek:

- daha doğal konuşsun ve sözü kesilebilsin;
- cevaplarının nereden geldiğini göstersin;
- neye baktığını hatırlasın;
- kiminle ne konuştuğunu ve hedeflerini bilsin;
- bunları Claude Code'a da açsın.

Başarı ölçütleri:

- Yeni bir AI çağrısı yok; hedefler mevcut akşam özeti çağrısına biniyor.
- Her şey Mac'te kalıyor.
- Model kaynak uyduramıyor.
- Kayıt yalnızca kullanıcı açarsa başlıyor.

## Kullanıcının kararları

| Soru | Karar |
|---|---|
| Etkinlik geçmişi | Kapalı başlar; açınca 30 gün tutulur |
| Ses | Mac'in doğal sesleri (Siri + Premium/Enhanced); bulut ses yok |
| MCP | Sadece okuma |
| Kişiler kaynağı | Toplantılar + hafıza; Contacts kullanılmaz |
| Hedef takibi | Akşam özetinde tek satır; ek çağrı yok |

## 10. Doğal ses

- Settings → General'daki "Read answers aloud" satırının altına **Voice** seçimi (`voice`) gelir.
  - `""` = Automatic: bugünkü Siri sesi (`say`, Spoken Content'in varsayılanı).
  - Diğer seçenekler: `say -v '?'` listesindeki Premium ve Enhanced sesler.
- Cevabın dili `NLLanguageRecognizer` ile algılanır. Seçili ses o dili konuşmuyorsa o dilde yüklü en iyi ses kullanılır (Premium > Enhanced > diğerleri). Hiç yoksa Settings bir kez "System Settings → Accessibility → Spoken Content'ten ses indir" notu gösterir.
- Akan cevap cümle sınırlarında parçalanır; her cümle sırayla `say` ile okunur, böylece konuşma cevap bitmeden başlar.

## 11. Konuşarak kesme

- Ayar: `bargeIn`, varsayılan açık; yalnızca `speak` açıkken anlamlı.
- Rabik konuşurken `AVAudioEngine` giriş düğümü `setVoiceProcessingEnabled(true)` ile (yankı engelleme) dinlenir.
- RMS seviyesi eşiğin üstünde yaklaşık 0,3 saniye kalırsa `shush()` çağrılır ve sıradaki cümleler atılır.
- Dinleme yalnızca konuşma süresince açıktır; ses kaydedilmez.

## 12. Kaynaklı cevaplar

- Yerel kayıtları okuyan yardımcı komutlar, bir istek içinde çalışırken (`RABIK_ASK` varsa) okudukları kayıtları `<ask>/sources.jsonl` dosyasına ekler. Bu komutlar: `--meeting-history`, `--history`, `--activity`, `--people`, `--recap read`, hafıza bilgileri.
- Satır biçimi: `{"kind": "meeting|day|activity|person|fact|ask", "id": "...", "label": "Weekly sync · Oct 23"}`.
- İstek bitince brain aynı kaydı bir kez gösterecek şekilde en fazla 4 kaynak seçer ve tek bir protokol satırı basar (`⌖ ` + JSON).
- Kutu bunları cevabın altında çip olarak gösterir. Tıklanınca:
  - toplantı: Settings → Meetings'te o toplantı açılır;
  - gün: o günün özeti açılır;
  - etkinlik: adres ya da dosya açılır;
  - kişi: Settings → People açılır;
  - bilgi: Settings → About you açılır.
- Çipler yalnızca gerçekten okunan kayıtlardan gelir; model bir kaynak adı yazsa bile çip olmaz.

## 13. Etkinlik geçmişi

- Ayar: `activity`, varsayılan kapalı (Settings → Privacy). `activityExclude`: kullanıcının eklediği uygulama paket kimlikleri.
- **Swift `Activity`:**
  - Öne gelen uygulama değişince ve açıkken 10 saniyede bir, öndeki pencereyi erişilebilirlik API'siyle okur:
    - başlık (`AXTitle`),
    - belge yolu (`AXDocument`),
    - tarayıcıda odaktaki web alanının adresi (`AXURL`).
  - Aynı pencere süregidiyorsa kaydın bitişi uzar. 10 saniyeden kısa kayıtlar yazılmaz.
  - Hiç kaydedilmeyenler:
    - başlığında Private, Incognito ya da InPrivate geçen pencereler;
    - Tor Browser;
    - şifre yöneticileri (1Password, Bitwarden, Keychain Access, Passwords);
    - Rabik'in kendisi;
    - `activityExclude` listesi;
    - ekran kilitliyken geçen süre.
- **Saklama:** `~/.config/rabik/activity/YYYY-MM-DD.jsonl` (klasör 0700, dosyalar 0600). Satır biçimi: `{"start", "end", "app", "bundle", "title", "url" | "path"}`. 30 günden eski dosyalar silinir. "Clear history" hepsini siler; anahtar kapanınca kayıt durur.
- **Brain `activity.py`:**
  - `--activity "<kelimeler, gün adı ya da tarih>"`: en iyi 8 eşleşmeyi süreleriyle döndürür ve kaynak olarak kaydeder.
  - Sistem istemine tek satırlık araç tarifi eklenir.
  - Akşam özeti girdisine o günün en uzun 3 belgesi ya da sayfası eklenir.

## 16. Kişiler

- Toplantı kaydına (`metadata.json`) o anki takvim etkinliğinin katılımcıları (`people`: ad + e-posta) eklenir.
- **Brain `people.py`** listeyi her seferinde kayıtlardan kurar, ayrı bir veri tabanı yoktur. Kaynaklar:
  - toplantı katılımcıları,
  - toplantılardaki konuşmacı adları,
  - `me.json`'daki People bilgileri.
- Birleştirme: aynı e-posta, ya da tek bir tam ada denk gelen ilk ad.
- Her kişi için: ad, e-posta, son görüşme, toplantılar (en yeni 10), bilinenler.
- `peopleHidden` listesindekiler gösterilmez.
- Komutlar:
  - `--people "<ad>"`: bir kişinin özeti; kaynak olarak kaydedilir.
  - `--people list`: Settings için tam liste.
- Settings'te yeni bir **People** sekmesi: arama, liste ve ayrıntı. Ayrıntıda toplantılara gidilebilir ve kişi gizlenebilir.

## 17. Hedefler

- `~/.config/rabik/goals.json`: `[{id, text, added, done}]`, en fazla 5 açık hedef.
- Ekleme:
  - sesle, anlık komutla ("my goal is …", "hedefim …");
  - Settings → General → Daily recap altındaki **Goals** listesinden.
- Kapatma: "… hedefini tamamladım" ya da "I finished the … goal" ile, veya Settings'teki onay kutusuyla.
- Akşam özeti istemine açık hedefler eklenir. Model, günün verisinde bir hedefe katkı varsa `goals: [{"goal", "note"}]` döndürür; `recap_check` yalnızca var olan hedef metinlerini kabul eder. Kartta "Goals" başlığı altında gösterilir.

## 15. Bağlayıcı önerisi

- Ayar: `connectorOffers`, varsayılan açık.
- Uygulama → bağlayıcı eşlemesi: Notion, Slack, Linear, Figma, Asana, Jira/Confluence (Atlassian), ClickUp, Monday. Eşleşme bağlayıcı adının içinde geçen kelimeyle yapılır.
- Eşleşen uygulama öne gelince, bağlayıcı `connected` listesinde değilse ve o uygulama susturulmamışsa kutunun köşesinde küçük bir kart çıkar. Bağlayıcı listesi en fazla 6 saatte bir okunur. Kart, örneğin "Rabik ve ajanların Notion'u okuyabilsin mi? Sayfalarını ve veritabanlarını arar, okur." der.
- Kartın düğmeleri:
  - Connect: mevcut `onboarding.grant("connectors")` akışı.
  - Not now: 7 gün sormaz.
  - Don't ask again: `connectorMuted`.
- Ekran paylaşımı, toplantı ya da etkin bir istek sırasında çıkmaz. Aynı oturumda her uygulama için en fazla bir kez görünür.

## 18. MCP sunucusu

- `rabik.py --mcp`: stdio üzerinden JSON-RPC 2.0, MCP `2025-06-18`. Desteklenen istekler: `initialize`, `tools/list`, `tools/call`, `ping`. Bağımlılık yok.
- Araçlar, hepsi `readOnlyHint: true`:
  - `search_memory`
  - `list_meetings`
  - `read_meeting`
  - `people`
  - `goals`
  - `daily_recap`
  - `search_activity`
- Kurallar:
  - "AI meeting summaries" kapalıyken `read_meeting` döküm vermez, yalnızca başlık ve yerel özet verir.
  - Etkinlik geçmişi kapalıyken `search_activity` "off" der.
  - Hassas (`sensitive`) hafıza bilgileri maskelenir.
- Settings → Agents:
  - **Add Rabik to Claude Code** düğmesi `claude mcp add --scope user rabik -- /usr/bin/python3 <rabik.py> --mcp` çalıştırır.
  - Claude Desktop için yapılandırma parçası kopyalanabilir olarak gösterilir.

## Hata durumları

- Erişilebilirlik izni yoksa etkinlik geçmişi kaydetmez ve Settings bunu söyler.
- `say` sesi yoksa Automatic'e düşülür.
- Mikrofon izni yoksa sözü kesme sessizce kapalıdır.
- `claude` yoksa MCP düğmesi devre dışıdır.
- MCP'de bozuk bir kayıt atlanır; araç hata yerine boş sonuç döner.

## Test

- Python birim testleri:
  - kaynak dosyası ve seçimi;
  - etkinlik araması, eleme ve saklama süresi;
  - kişi birleştirme;
  - hedef ekleme ve kapama, özetteki hedef satırının denetimi;
  - bağlayıcı eşlemesi;
  - MCP el sıkışma, araç listesi, araç çağrıları ve salt okunurluk.
- Swift kaynak denetimleri: ses seçimi, cümle kuyruğu, voice processing, etkinlik elemesi.
- Settings ve kutu sayfa testleri (`RABIK_ALLOW_HOST_UI=1`): Voice seçimi, People sekmesi, Goals, kaynak çipleri, bağlayıcı kartı.
- Gerçek kullanımda doğrulanacaklar TEST-PLAN'a eklenir: ses kalitesi, sözü kesme, AX ile adres okuma, Claude Code'da MCP.

## Uygulama sırası

1. 12, kaynak altyapısı.
2. 10–11.
3. 13.
4. 16.
5. 17.
6. 15.
7. 18.

Her adım ayrı commit'lenir; sonunda iki Python sürümünde tam test takımı çalıştırılır, ardından release build alınıp kurulur.
