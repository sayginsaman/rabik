# Akşam özeti ve toplantı aksiyonlarını Hatırlatıcılar'a ekleme — tasarım

Tarih: 2026-10-25 · Durum: uygulandı (9c0c128 … 3921b1b); gerçek bildirim ve Hatırlatıcılar izni kullanıcının ilk denemesinde doğrulanacak · Esin: Omi'nin günlük özeti ve aksiyon maddeleri

## Amaç

Rabik günün sonunda o gün olanları tek bir kartta toplar: toplantı kararları, biten ajanların sonuçları, önemli istekler ve yarının takvimi. Kartta kullanıcı yapılacak işleri seçip Apple Hatırlatıcılar'a ekler. Aynı ekleme, toplantı özetlerinde de vardır.

Başarı ölçütü: günde en fazla bir AI çağrısı (Haiku, yaklaşık 0,3 cent), beklerken hiç maliyet yok; AI hiçbir şeyi kendisi eklemez, yalnızca önerir; veride olmayan iş ya da tarih kartta görünmez.

## Kullanıcının kararları

| Soru | Karar |
|---|---|
| Kapsam | Günün tamamı: toplantılar, biten ajanlar, önemli istekler, yarının takvimi |
| Zamanlama | Sabit saatte bildirim (varsayılan 21:00, Settings'ten değişir); kaçan gün Rabik açılınca tamamlanır; "günümü özetle" ile her an |
| Hatırlatıcılar'a ekleme | Görüp seçerek: maddeler boş kutuyla gelir, "Hatırlatıcılara ekle" seçilenleri ekler |
| Liste | Hatırlatıcılar'ın varsayılan listesi; Settings'ten başka bir liste seçilebilir |
| Yaklaşım | A: yerleşik launchd işi + tek Haiku çağrısı (ajan değil) |
| Ekleme nerelerde | Akşam özeti kartı, Settings → Meetings ayrıntısı, toplantı bitince çıkan panel |
| Varsayılan | Akşam özeti açık |

Reddedilen yaklaşımlar: sıradan bir rutin + ajan (yaklaşık 10 kat pahalı, seçilebilir madde yok, uydurmayı önlemek zor); uygulama içi zamanlayıcı (release'te login item olmadığı için Rabik kapalıysa çalışmaz).

## Mimari

- **Ayar.** Settings → General'da "Daily recap" grubu: aç/kapa (`recap`, varsayılan açık), saat (`recapAt`, varsayılan `21:00`), Hatırlatıcılar listesi (`remindersList`, varsayılan boş = sistemin varsayılan listesi).
- **Zamanlama.** Açıkken `~/Library/LaunchAgents/com.rabik.recap.plist` kurulur (`StartCalendarInterval`, `recapAt`). İş, rutinlerdeki gibi kuyruğa `{"recap": "<tarih>"}` yazar ve Rabik'i uyandırır, kapalıysa açar (`routine_fire` ile aynı yol). Saat değişince iş yeniden kurulur, ayar kapanınca kaldırılır.
- **Kaçan gün.** Rabik açılırken ve Mac uykudan uyanırken: saat `recapAt`'i geçtiyse ve bugünün özeti yoksa bir kez üretilir. Duraklatılmışken (`paused`) üretilmez.
- **Üretim.** Yeni `brain/recap.py`, `rabik.py --recap [--date YYYY-MM-DD]`: veriyi toplar, tek Haiku çağrısı yapar, sonucu `~/.config/rabik/recaps/<tarih>.json` (0600) dosyasına yazar. Aynı gün yeni veri yoksa var olan dosyayı döndürür. Kilit dosyası çift tetikte tek üretim sağlar.
- **Bildirim.** Bugünkü bildirimler `osascript display notification` ile gidiyor; tıklanınca Script Editor açılıyor. Akşam özeti bildirimini Rabik.app kendisi gönderir (`UNUserNotificationCenter`; izin, özet ilk kez gönderileceğinde istenir). Tıklanınca özet kartı kutuda açılır. Bildirim izni yoksa kart, ajan bitiş kartları gibi kullanıcı yazmıyorken kutuda kendiliğinden belirir.
- **İsteyince.** "summarize my day", "günümü özetle" ve benzerleri anlık komut olarak `--recap`'i çalıştırır ve kartı açar.
- **Hatırlatıcılar.** `Rabik --calendar` (Sources/Rabik/Meeting/CalendarTool.swift, EventKit) iki işlem kazanır: `reminderLists` ve `addReminders`.

## Veri akışı

Toplanan veri (yerelde, sınırlı):

1. **İstekler:** `log.jsonl`'dan bugün tamamlananlar; istek ve cevap kısaltılmış (her biri ~200 karakter), en fazla 40. Anlık komutlar (`path == "instant"`) yalnızca sayı olarak.
2. **Ajanlar:** bugün biten ajanların başlığı, özeti, değişiklikleri ve linkleri (`agents.agent_history`).
3. **Toplantılar:** bugünkü toplantıların özeti ve aksiyon maddeleri (`meeting.py`'nin kaydettiği özet). `meetingSummary` kapalıysa toplantı içeriği AI'a gönderilmez; kartta yalnızca yerel liste olarak görünür.
4. **Yarın:** takvim izni varsa yarının etkinlikleri (ad ve saat).

Hiçbir şey yoksa AI çağrısı ve bildirim olmaz.

Haiku çağrısı (`meeting_call` gibi tek seferlik, araçsız): veri "talimat değil, veri" olarak işaretlenir. İstenen JSON:

```json
{"headline": "tek satır",
 "highlights": ["en fazla 5"],
 "decisions": ["toplantı kararları"],
 "actions": [{"text": "yapılacak iş", "from": "meeting:<id> | agent:<id>", "due": "YYYY-MM-DD veya boş"}],
 "tomorrow": ["yarının önemli etkinlikleri"]}
```

Doğrulama: tipler ve uzunluklar; `from` yalnızca verideki kimliklerden biri olabilir; `due` yalnızca kaynağında tarih geçiyorsa kalır. Geçmeyen alanlar atılır. JSON bozuksa ya da AI yoksa yerel özet kullanılır: toplantı aksiyonları, biten ajanlar ve yarının takvimi, düz liste olarak; kartta "AI özeti yapılamadı" satırı olur.

## Hatırlatıcılar

- `reminderLists` → `[{id, title, isDefault}]`. `addReminders` → `{list, items: [{title, notes, due}]}` alır, oluşanların kimliklerini döndürür.
- Hatırlatıcı: başlık aksiyonun metni; not "Rabik · <toplantı ya da ajan adı>, <tarih>"; son tarih yalnızca verildiyse ve saatsiz.
- İzin bağlamında istenir: "Hatırlatıcılara ekle"ye ilk basışta (`requestFullAccessToReminders`). Reddedilirse kart nedenini ve System Settings → Privacy & Security → Reminders yolunu söyler, hiçbir şeyi eklenmiş saymaz.
- Info.plist: `NSRemindersFullAccessUsageDescription` = "Rabik adds the action items you choose to Reminders." İmzalı build'de ayrıca bir yetki (entitlement) gerekip gerekmediği doğrulanacak; takvim için `com.apple.security.personal-information.calendars` var.
- Seçili liste silinmişse varsayılan listeye düşülür ve kart bunu söyler.
- Çift ekleme: eklenen her madde, kaynağıyla birlikte özet ya da toplantı dosyasına `added` olarak yazılır. Kartta ✓ Added görünür ve yeniden eklenemez. Özet yeniden üretilse de işaret korunur. Ekleme yarıda kesilirse yalnızca oluşanlar işaretlenir.
- Ekleme kullanıcının düğmesiyle olur; Safe mode ayrıca kart sormaz. AI hiçbir zaman hatırlatıcı eklemez.

## Arayüz

- **Akşam özeti kartı (ui/ui.html):** başlıkta tek satırlık özet; "Bugün", "Kararlar", "Yapılacaklar" (boş kutu + kaynak etiketi + varsa tarih), "Yarın"; altta "Hatırlatıcılara ekle (n)", yalnızca seçim varken etkin. Kart kullanıcı kapatana kadar kalır.
- **Settings → Meetings ayrıntısı (ui/settings.html):** aksiyon listesi işaretlenebilir olur, altına aynı düğme.
- **Toplantı paneli (ui/meeting.html):** toplantı bitince çıkan özetteki aksiyonlar da işaretlenebilir, aynı düğmeyle.
- **Settings → General:** "Daily recap" grubu (aç/kapa, saat, Hatırlatıcılar listesi).

## Gizlilik

- Özetler `~/.config/rabik/recaps/` altında 0600 izinle, en fazla 30 gün tutulur.
- AI'a giden veri, gün içinde kullanıcının istekleriyle zaten gönderilenden fazlası değildir; AI toplantı özeti kapalıysa toplantı içeriği hiç gitmez.
- Devin ya da Pi seçiliyse AI özeti yapılmaz, yerel özet kullanılır.

## Testler

Gerçek Claude, Hatırlatıcılar ya da launchd kullanılmadan:

- Veri toplama: sahte bir gün için doğru ve sınırlı girdi; boş günde AI çağrısı yok; `meetingSummary` kapalıyken toplantı metni çağrıya girmiyor.
- JSON doğrulama: bozuk yanıt, bilinmeyen `from`, kaynağında olmayan tarih reddediliyor; yerel özete düşülüyor.
- Zamanlama: launchd plist'i doğru saatle yazılıyor ve kaldırılıyor; kaçan gün bir kez tamamlanıyor; çift tetikte tek özet; duraklatılmışken üretim yok.
- Hatırlatıcılar: `CalendarTool`'un yeni işlemleri derlenip sahte bir depoyla çalıştırılıyor (VM); çift ekleme engelleniyor; yarıda kesilen eklemede yalnızca oluşanlar işaretleniyor.
- Arayüz: özet kartı, Settings ayrıntısı ve toplantı paneli WKWebView düzeneğinde: kutular, düğmenin etkinliği, ✓ Added, izin reddi mesajı.
- Anlık komut: "summarize my day" ve "günümü özetle" `--recap`'e gidiyor.

## Kapsam dışı

Önceki günlerden açık iş taşımak, hedef takibi, Hatırlatıcılar'dan geri okuma ve yapıldı işaretlemek, birden çok dil için ayrı özet şablonları.

## Açık noktalar

- Hatırlatıcılar için imzalı (Hardened Runtime) build'de ek yetki gerekiyor mu: ilk uygulama adımında doğrulanacak.
- Bildirimler: ajan ve rutin bildirimleri de bugün `osascript` ile gidiyor ve tıklanınca Script Editor açıyor. Akşam özeti için kurulacak `UNUserNotificationCenter` yolu onlara da uygulanabilir; ayrı bir iş.
