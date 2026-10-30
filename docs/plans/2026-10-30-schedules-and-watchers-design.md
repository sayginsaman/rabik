# Zamanlanmış görevler ve kendi kendine hareket eden izleyiciler — tasarım

Tarih: 2026-10-30 · Durum: onaylandı, uygulanıyor

## Sorun

Kullanıcı iki şey istiyor:

- "Bugün 20:00'de Discord'a gir, Ali'ye 'geliyorum' yaz" ya da "her pazartesi ve perşembe 9'da …" gibi görevler kurmak. Bugün Rabik bunları kuramıyor:
  - rutinler yalnızca "her gün", "hafta içi" ve "her N dakika" olabiliyor;
  - tek seferlik görev ve belirli günler yok;
  - görev mesaj göndermek gibi onay isteyen bir şeyse, zamanı gelince Mac başında birinin onaylaması gerekiyor.
- "ChatGPT izin isterse onayla" gibi bir izleyici kurmak: Rabik bir pencereyi izlesin, istenen düğme göründükçe ona bassın. Bugün izleyici:
  - tek seferlik ve en fazla 3 saat;
  - her adımı AI'a yaptırıyor;
  - Safe mode arka planda "Allow" düğmesine basmayı engelliyor.

## Kullanıcının kararları

| Soru | Karar |
|---|---|
| Otomatik onay izleyicisi ne kadar sürsün | Kullanıcı durdurana kadar; Rabik yeniden açılınca devam eder |
| Zamanı gelince onay isteyen görev | Kurarken bir kez onaylanır, zamanı gelince sormadan yapılır |
| Saati kaçan tek seferlik görev | Settings'ten ayarlanabilir; varsayılan: yapma, bildir |

## Zamanlanmış görevler

**Türler.**

- `time`, şu günlerde: `daily`, `weekdays`, `weekends` ya da gün listesi (`mon,thu`).
- `once`: `YYYY-MM-DD`, `today` ya da `tomorrow`, artı `HH:MM`.
- `interval`: her N dakika.

**Komut.**

- `rabik.py --routine add time HH:MM <günler> "<istek>" [mode] [--unattended]`
- `rabik.py --routine add once <tarih> HH:MM "<istek>" [mode] [--unattended]`
- `rabik.py --routine add interval SANİYE "<istek>" [mode] [--unattended]`

**Zamanlama.** Her görev bir launchd işi:

- haftalık günler `StartCalendarInterval` listesi olur;
- tek seferlik görev `{Month, Day, Hour, Minute}` olur. Yıl kontrolü Rabik'te yapılır.

**Tek seferlik görevin ömrü.**

- Ajan başladığı anda görev ve işi silinir.
- Saati kaçmış bir görev, Mac uyanınca ya da Rabik açılınca (`routine_repair`) `routineLate` ayarına göre ele alınır:
  - `skip` (varsayılan): 15 dakikadan geç kaldıysa yapılmaz, "kaçırıldı" bildirimi gelir.
  - `2h`: 2 saate kadar geç yapılır.
  - `always`: ne kadar geç olursa olsun yapılır.
- Ayar Settings → General → Scheduled routines bölümündedir.

**Gözetimsiz görevler (`--unattended`).**

- Kurulurken Safe mode bir kart gösterir: "Run this later without asking?" Kartta görevin tam metni vardır.
- Kullanıcı onaylarsa görev kaydına `unattended: true` yazılır.
- Zamanı gelince başlayan ajanın izin dosyasına (`allow-task`) `*` yazılır. Bu, "Always allow for this task" seçeneğinin baştan verilmiş hâlidir.
- Rabik'in kesin yasakları sürer: `rm`, `sudo`, gizli alana yazmak.
- Sonuç her zaman bildirimle gelir.
- `--unattended` olmayan bir görev kurulurken kart çıkmaz. Onay isteyen adımlar, zamanı gelince ajanın kartıyla sorulur.

**Etiketler.** Görev kaydına okunur bir etiket yazılır ve Settings bunu gösterir:

- "Mondays and Thursdays at 9:00 AM"
- "Once on Fri, Oct 30 at 8:00 PM"

## Kendi kendine basan izleyiciler

**Komut.** `rabik.py --watch press "<uygulama>" "<düğme>[|<düğme 2>]"`

- Kurulurken bir kart çıkar: "Click this whenever it appears?" Kartta uygulama ve düğme adı yazar.
- Onaylanırsa izleyici `watches.json` dosyasına yazılır.

**Çalışma.**

- İzleyici Rabik.app'in içinde çalışır; Python süreci yoktur. Uygulama dosyayı izler ve açılışta yükler.
- 2 saniyede bir, o uygulamanın pencerelerinde (sayfalar ve diyaloglar dahil) başlığı ya da açıklaması tam olarak verilen ada eşit bir `AXButton` arar. Arama sınırlıdır: en fazla 25 seviye ve 3000 öğe.
- Bulursa `AXPress` ile basar. Odak değişmez, imleç hareket etmez.
- Rabik'in kendi pencerelerine hiçbir zaman basmaz.

**Bildirim.** Her basıştan sonra bildirim gelir (dakikada en fazla bir, sayılarıyla). Örnek: "Approved in ChatGPT: Allow (3 times)".

**Durdurma.** İzleyici sen durdurana kadar çalışır:

- "izlemeyi durdur" ile (`--unwatch`, tümü ya da bir kimlik);
- Settings → General → Watches listesindeki Stop düğmesiyle.

**Listeleme.** `--watches` çalışan izleyicileri listeler. Eski tek seferlik metin izleyicileri olduğu gibi kalır.

## İstem bütçesi

Kurulu istem 10.049 karakterde, sınır 10.050. Bu yüzden:

- Zamanlama ve izleme talimatları sistem isteminden çıkar.
- Bunların yerine, istek bu tür bir şeyden söz ettiğinde (İngilizce ve Türkçe sözcüklerle) isteğe bir yardım bloğu eklenir. Sözcük örnekleri: "every", "tomorrow", "at 8", "whenever", "her", "saat", "yarın", "izin isterse".
- Sistem isteminde tek kısa satır kalır; bu satır ayrıca `--routine --help` ve `--watch --help` komutlarına yönlendirir.

## Test

- **Rutinler:** yeni türlerin doğrulanması, etiketler ve launchd takvimleri; tek seferlik görevin geç kalma kuralları ve silinmesi; komut ayrıştırma (`today`, `tomorrow`, geçmiş saat hatası).
- **Policy:** `--unattended` ve `--watch press` için kart; düz `--routine add` için kart çıkmaması; `allow-task` içindeki `*`.
- **Ajanlar:** gözetimsiz bir rutin ajanı izin dosyasıyla başlar; tek seferlik görev başlayınca silinir.
- **İzleyici:** kayıt, durdurma, listeleme; Swift düğme bulma ve basma mantığı (sahte bir erişilebilirlik ağacı).
- **İstem:** sınır testi ve yardım bloğunun hangi isteklerde eklendiği.
- **Settings:** yeni etiketler, Watches listesi ve geç kalma seçimi.
