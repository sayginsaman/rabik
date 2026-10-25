# Atticus — Kod Denetimi (Audit) Raporu

Tarih: 24 Ekim 2026 · Sürüm: `VERSION` = 1.5.2 · Kapsam: projenin tamamı (git deposu değil, indirilmiş kopya)

> Not: Projede `main.py` yok. Backend'in tamamı **`atticus.py`** içinde (7.650 satır, 480 KB). macOS uygulamasının tamamı da aynı şekilde tek dosyada: **`Atticus.swift`** (7.324 satır, 543 KB). Bu rapor ikisini de kapsıyor.
>
> **Satır numaraları** baseline commit `b67b701`'e göredir. Ürün sonradan Rabik olarak yeniden adlandırıldı (`atticus.py` → `rabik.py`, `Atticus.swift` → `Rabik.swift`); orijinal satırları görmek için `git show b67b701:atticus.py`.

---

## 0. Özet

| Alan | Not | Tek cümle |
|---|---|---|
| Maintainability | **D** | 2 dev dosya, 114 modül-seviyesi global, fonksiyon attribute'ları ve `os.environ` üzerinden gizli veri akışı; değişiklik yapmak için tüm dosyayı kafada tutmak gerekiyor. |
| Stability | **C+** | Timeout ve atomik yazma disiplini iyi; ama thread'ler arası paylaşılan global durum, sinyal handler karmaşası ve sessizce yutulan hatalar var. |
| Performance | **B−** | İstek başına onlarca kısa ömürlü süreç (python, osascript, claude); 20 ms'lik polling döngüleri; hiç döndürülmeyen (rotate) loglar. |
| Security (safe mode) | **C** | Ana istekler sandbox **dışında** çalışıyor; tek koruma regex deny-list. Doğrulanmış atlatma örnekleri var (bkz. P1). |

**En önemli 8 bulgu**

| # | Önem | Bulgu | Yer |
|---|---|---|---|
| P1 | 🔴 Yüksek | Safe mode'da ana istekler sandbox'sız + `bypassPermissions` ile çalışıyor; risk kontrolü regex deny-list. `python3 -c "…rmtree…"`, `truncate -s 0 dosya`, `cp /dev/null dosya`, `pbpaste > dosya`, `atticus.py --search x > dosya` onay kartı **çıkarmadan** geçiyor (çalıştırılarak doğrulandı). README "sandbox'ta çalışır" diyor. | `atticus.py:580-646`, `706-821`, `4969-4998` |
| P2 | 🟠 Orta | Ölü Gumroad lisans kodu canlı yolda: kullanıcı "key bindings" / "key shortcuts" derse kelime `api.gumroad.com`'a gönderiliyor ve "That key did not work" cevabı dönüyor (doğrulandı). | `43-46`, `3342-3362`, `7362-7371` |
| M1 | 🟠 Orta | Tek dosya: 321 top-level fonksiyon, `main()` 562 satır, `run()` 271 satır; 54 CLI bayrağı tek `if` zincirinde. | tüm dosya |
| M2 | 🟠 Orta | Gizli yan kanallar: `run.ok`, `run.ran`, `fast.cmds`, `replay.failed_at` … (18 fonksiyon-attribute), `TURN`/`STOPPING` globalleri, parametre yerine `os.environ` (29 farklı `ATTICUS_*` değişkeni, ~178 okuma). Modüllere bölmenin önündeki 1 numaralı engel. | `run`, `fast`, `replay`, `main` |
| M3 | 🟠 Orta | "Bu tehlikeli mi?" mantığı 6 ayrı regex'te + Swift'te 1 kopya; birbirinden farklı kurallar. | `572-597`, `1641`, `2348`, `2750` |
| F1 | 🟡 Orta | Her helper çağrısı (her tool call'da `--gate` hook'u dahil) 7.650 satırlık modülü baştan yükleyen yeni bir Python süreci; derleme ~80 ms (ölçüldü). Satır 2'deki `sh`/Python polyglot hilesi tam da bunun için var. | `1-2` |
| F2 | 🟡 Orta | `log.jsonl` ve ajan logları hiç döndürülmüyor; Settings (`--state`), `--budget`, `history()`, `ran_programs()` her seferinde tüm dosyayı okuyor. 1 yıllık kullanım simülasyonu (15,8 MB): 134–181 ms ve doğrusal büyüyor. | `3509`, `6026`, `6097`, `7228` |
| S1 | 🟡 Orta | Dosya tabanlı IPC 20 ms polling ile: `relay()`, `ask_user()`, `wait_commit()`; ajan servisi 150 ms'de bir tüm ajan klasörlerini tarıyor. | `649`, `829`, `5011`, `4806` |

**Swift, UI, test ve build tarafındaki en önemli bulgular** (ayrıntılar §5–§6)

| # | Önem | Bulgu | Yer |
|---|---|---|---|
| SW-S1 | 🔴 Yüksek | Settings'te pipe deadlock: Swift, `--state` çıktısını okumadan sürecin bitmesini bekliyor. Çıktı büyüyünce Settings boş kalıyor ve her açılışta bir Python süreci asılı kalıyor. | `Atticus.swift:4589-4596` |
| SW-S2 | 🔴 Yüksek | `Prefs.d` kilitsiz global sözlük: ana thread yazarken arka plan thread'i her 1,5 sn'de okuyor. Ara sıra çökme riski. | `Atticus.swift:202-225`, `4562-4566` |
| SW-P1 | 🔴 Yüksek | Ekrana çizim rehberinde her adımın hedefi ana thread'de AX ile aranıyor; adım başına ~2 sn'ye kadar donma. | `Atticus.swift:1367-1372`, `6149-6163` |
| B1 | 🔴 Yüksek | İmzasız otomatik güncelleme: 6 saatte bir `main`'i `git pull` + `build.sh`, ayrıca `curl \| bash` kurulum. (Rabik'in `.dmg` modelinde kapalı.) | `Atticus.swift:4296-4327` |
| SW-SEC1 | 🟠 Orta | WebView'larda CSP ve navigasyon politikası yok; overlay'de çalışan bir script safe-mode onay kartını kendi kendine onaylayabilir. | `Atticus.swift:1976-2177` |
| T1 | 🟠 Orta | Testler `atticus`'un 120 ismini 1.245 yerde monkeypatch ediyor; naif bölme bu patch'leri sessizce etkisiz kılar ve testler gerçek `claude`'u başlatabilir. Refactor'dan **önce** güvenlik ağı gerekli. | `tests/` |

---

## 1. Yöntem

- `atticus.py` satır satır baştan sona okundu. `Atticus.swift`, `ui/*`, `tests/`, build/CI dosyaları paralel incelendi (§5–§6).
- Ölçümler ve doğrulamalar ayrı bir scratch klasöründe, `ATTICUS_DIR` izole edilerek yapıldı; kullanıcı ayarlarına dokunulmadı:
  - AST metrikleri (fonksiyon uzunlukları, global sayısı, yan kanallar).
  - `risky()` fonksiyonu gerçek komutlarla çağrıldı (P1).
  - Derleme/import süreleri ve büyük `log.jsonl` ile okuma süreleri ölçüldü (F1, F2).
  - Test paketi (815 test) Python 3.14 ve Apple'ın Python 3.9'u ile, hem orijinal yolda hem de boşluksuz bir kopyada çalıştırıldı; ayrıca in-process coverage ölçüldü (§6).
  - Swift tarafında iki iddia `swiftc` ile ayrıca denendi: `Process` retain cycle olmadığı ve modül adının çıktı dosyasından geldiği.
- Denetim sırasında kod değiştirilmedi.

---

## 2. Mimari — sistem nasıl çalışıyor?

```
 Atticus.app (Swift, tek süreç, menü çubuğu)
   │  hotkey, konuşma tanıma, WKWebView overlay (ui/*.html), AX/ekran yakalama
   │
   ├─ atticus.py --wait          (her istek için bir "worker" süreci, stdin'den isteği alır)
   │     └─ claude -p ... --permission-mode bypassPermissions   (istekten önce ısıtılır)
   │            └─ her tool call → PreToolUse hook: /bin/sh atticus.py --gate   (yeni Python süreci)
   │            └─ AI'nin bash komutları: atticus.py --place/--hands/--web/--look …  (yeni Python süreci)
   │                    └─ bunlar da geri Swift'i çağırıyor: Atticus --hands / --window-target / --look …
   ├─ atticus.py --agents        (uzun ömürlü arka plan ajan servisi, stdin/stdout JSON)
   ├─ atticus.py --fast / --dictate-cleanup-wait / --meeting-live / --state / … (37 farklı bayrak)
   └─ ~/.config/atticus/*  ve istek başına geçici klasör  → süreçler arası dosya tabanlı IPC
```

Refactor açısından kritik gerçekler:

1. **`atticus.py` bir sunucu değil, bir CLI.** Bir istekte onlarca kez yeni süreç olarak başlatılıyor. Bu yüzden başlangıç maliyeti (import) doğrudan kullanıcı gecikmesi.
2. **`atticus.py` yolu dış sözleşme.** Swift 37 bayrakla çağırıyor; sistem prompt'u AI'ye mutlak yolu öğretiyor (`ME`); gate `basename == 'atticus.py'` kontrolü yapıyor; kullanıcının öğrenilmiş kısayolları (`skills.json`) bu yolu içeren komutlar olarak **diskte saklı**. Dosya yeniden adlandırılırsa kaydedilmiş kısayollar bozulur. → Giriş dosyası aynı adla kalmalı.
3. Swift ↔ Python protokolü belgelenmemiş: stdout'ta satır önekleri (`· ▸ ✓ ! ? ◇ ⤴ ⇢ ▣ @ ✎ ↺ ⚙ ▤ i …`), 29 ortam değişkeni, istek klasöründeki dosya adları (`handed-off`, `searched`, `focus-requested`, `hands-*`, `.q`, `point` …).

---

## 3. `atticus.py` sorumluluk haritası

Bölme planının temeli bu tablo (satır aralıkları yaklaşık):

| Satırlar | Sorumluluk | Önerilen modül |
|---|---|---|
| 1–56, 490–493 | Bootstrap: yollar, sürüm, helper komut sabitleri, `PATH` değişikliği, PostHog anahtarı, Gumroad (ölü) | `paths.py` |
| 57–391 | "About you" profil deposu, Contacts/Mail içe aktarma (JXA) | `memory.py` |
| 393–489 | Ayarlar (`pref`), model yönlendirme, özel sunucu, yerel sunucu keşfi | `prefs.py` |
| 495–570, 3586, 3798–3819, 6194, 6312, 6388 | Prompt metinleri (SYSTEM, AGENT_SYSTEM, MEETING, DICTATE, DRAW_HELP …) | `prompts.py` |
| 571–821, 3987–4080 | Güvenlik kapısı: deny-list'ler, `risky()`, `gate()`, "bu görev için izin ver", ajan URL izin listesi | `policy.py` |
| 823–944, 5011–5063 | Kullanıcıya soru/kart IPC'si: `ask_user`, `pick`, `relay`, `set_switch`, seçim kartı | `interaction.py` |
| 946–1093, 1532–1625 | macOS yardımcıları: `osa`, ekranlar, ön uygulama, odak koruma, uygulama adları | `macos.py` |
| 1096–1230, 2160–2185 | Pencere yerleştirme | `windows.py` |
| 1242–1350 | Açma/gösterme (`show`, arka plan sekmesi) | `apps.py` |
| 1352–1530 | Spotify | `spotify.py` |
| 1633–2000 | Öğrenilmiş kısayollar, replay, workflow'lar | `skills.py` |
| 2002–2158 | Anında komutlar (AI'siz hızlı yol, `fast()`) | `instant.py` |
| 2187–2265, 2347–2700 | Ekran görüntüsü, web fetch/search, tarayıcı otomasyonu (`web()`) | `screen.py`, `web.py` |
| 2267–2345 | Overlay için adım etiketleri (`label`) | `labels.py` |
| 2717–3095 | "Hands" (Swift üzerinden native AX eylemleri), menü çubuğu | `hands.py` |
| 3097–3340 | Geçmiş, rutinler (launchd), "watch" | `routines.py`, `watch.py` |
| 3342–3362 | Gumroad lisans (ölü kod) | **silinmeli** |
| 3365–3488 | Telemetri (PostHog), hata raporlama, temizleme | `telemetry.py` |
| 3490–3657 | Çıktı protokolü (`say`), istek kaydı (`TURN`, `checkpoint`, `log_turn`), ipuçları | `protocol.py`, `turn.py` |
| 3660–3796, 4939–5008, 5439–5594 | AI istemcileri: Claude, Devin, Pi süreç yönetimi | `clients.py` |
| 3822–3958, 5066–5155 | Hand-off direktifleri, isimli ajanlar, `MainMove` | `handoff.py` |
| 3960–4937 | Ajan yardımcıları + `Agents` servisi (580 satırlık sınıf) | `agents.py` |
| 5157–5427 | `run()`: bir isteği modelden geçiren ana döngü | `ask.py` |
| 5597–5777 | Bağlam toplama: seçim, işaret, çizim, pencere metni | `context.py` |
| 5779–5882 | Hafıza kuralları (`memory.md`) | `memory.py` |
| 5884–6024 | Ekrana çizim doğrulama/gönderme | `drawing.py` |
| 6086–6191, 6194–6267 | CLI yardım önbelleği, Kişiler, Takvim | `toolhelp.py`, `calendar.py` |
| 6303–6383, 6663–6983 | Toplantı yardımcısı ve arşivi | `meeting.py` |
| 6388–6660 | Dikte temizleme | `dictation.py` |
| 7002–7300 | CLI dağıtımı (54 bayrak, tek `if` zinciri) | `cli.py` |
| 7301–7563 | Ana istek orkestrasyonu (`main()`'in ikinci yarısı) | `ask.py` |
| 7566–7646 | `--selftest` (modül globallerini monkeypatch ediyor) | `tests/`'e taşınmalı |

---

## 4. `atticus.py` bulguları

Her bulgu: önem · yer · kanıt · öneri. "Doğrulandı" = kod çalıştırılarak teyit edildi.

### 4.1 Güvenlik ve doğruluk

**P1 — Safe mode ana istekleri sandbox'lamıyor; deny-list atlatılabiliyor** · 🔴 Yüksek · doğrulandı
- `start_claude()` sandbox ayarını yalnızca ajanlara veriyor (`4969-4971`); ana istek `--permission-mode bypassPermissions` ile başlıyor (`4998`). `gate()` izin verdiği her Bash komutuna `dangerouslyDisableSandbox: True` ekliyor (`731-733`). Yorum da bunu söylüyor (`581`). Yani ana istekte tek bariyer `risky()` regex listesi.
- `risky()` ile doğrulanan sonuçlar (boş string = onay sorulmadan çalışır):

  | Komut | `risky()` |
  |---|---|
  | `python3 -c "import shutil; shutil.rmtree('…/Documents')"` | `''` |
  | `python3 -c "open('~/.zshrc','w').write('')"` | `''` |
  | `truncate -s 0 ~/Documents/thesis.docx` | `''` |
  | `cp /dev/null ~/Documents/thesis.docx` | `''` |
  | `pbpaste > ~/Documents/thesis.docx` | `''` |
  | `<atticus.py> --search 'x' > ~/Documents/thesis.docx` | `''` |
  | `mdfind -name foo > ~/.zshrc` | `''` |
  | `echo hi > ~/.zshrc` (karşılaştırma) | `'Change a file?'` |

- İki ayrı kök neden: (a) deny-list mantığı doğası gereği eksik kalır (yorumda da "a deny list, not proof of safety" yazıyor, `1640`); (b) `QUIET` önekli parçalarda (`pbpaste`, `open `, `mdfind `, tüm helper'lar) `continue` ile **yönlendirme (`>`) kontrolü de atlanıyor** (`633-634`).
- Neden önemli: Sistem prompt'u ekran/web/e-posta metnini "untrusted" diye işaretliyor ama prompt injection veya model hatası tek bir yanlış komutla kullanıcı dosyasını silebilir; kullanıcı README'deki "sandbox" vaadine güveniyor.
- Öneri: (1) Ana istekleri de sandbox'ta çalıştırın; helper'lar için zaten `SAFE_OUT`/`excludedCommands` mekanizması var. (2) Kısa vadeli yama: yönlendirme kontrolünü `QUIET` atlamasından önce yapın; `action_kind()`'daki "yorumlayıcılar (python/perl/node/ruby/osascript) her zaman sorulur" kuralını (`4004`) `risky()`'ye de uygulayın. (3) Politika tek modülde, tek tablo-tabanlı test setiyle.

**P2 — Ölü Gumroad lisans kodu canlı istek yolunda** · 🟠 Orta · doğrulandı
- `GUMROAD_PRODUCT = ''` (satış yok) ama `main()` her istekte `key\W+([\w-]{8,})` regex'ini çalıştırıyor (`7362`). "key bindings", "key shortcuts", "key: abcdefgh" eşleşiyor → `activate()` kelimeyi `api.gumroad.com`'a POST ediyor ve kullanıcıya "That key did not work. Copy it from your Gumroad receipt…" diyor.
- Öneri: `GUMROAD_PRODUCT`, `BUY`, `KEY_FILE`, `licensed()`, `activate()` ve `main()`'deki dalı tamamen silin.

**P3 — AppleScript tırnaklama tutarsız** · 🟢 Düşük
- `osa_quote()` var ama 6 yerde aynı kaçış elle tekrar yazılmış (`1253`, `1275`, `2354`, `2371`, `2442`, `2766`) ve bazı yerlerde hiç kullanılmamış: `front()` (`1054`), `request_screen()` (`1091`), `show()` (`1341`, `1348`), `web()` (`2601`), `main()` (`7405`). Değerler çoğunlukla System Events'ten geldiği için risk düşük, ama ileride model kaynaklı bir isim bu yollara girerse AppleScript injection olur.
- Öneri: AppleScript'e değer geçirmenin tek yolu `on run argv` + argüman olsun (kodun bir kısmı zaten böyle yapıyor).

### 4.2 Maintainability

**M1 — Tek dosya, dev fonksiyonlar** · 🟠 Orta
- 7.650 satır; 321 top-level fonksiyon/sınıf, 114 modül-seviyesi isim; 25 fonksiyon >50 satır, 7 fonksiyon >100 satır.
- En uzunlar: `main` 562 · `run` 271 · `web` 160 · `fast` 148 · `Agents.read` 116 · `gate` 115 · `place` 103.
- 353 satır >150 karakter, 80 satır >200 karakter (en uzun 887). Noktalı virgülle birleştirilmiş çoklu ifadeler yaygın (`a = …; b = …; self.save(row)`).
- Öneri: §7'deki paket yapısı; `main()`'i `cli.py` (bayrak → handler tablosu) ve `ask.py` (istek orkestrasyonu) olarak ikiye bölün.

**M2 — Gizli veri akışı: fonksiyon attribute'ları, globaller, `os.environ`** · 🟠 Orta
- Dönüş değeri yerine fonksiyon üzerine yazılan durum: `run.cmds/ran/error/ok/handoff/handoffs/observed/work/why`, `fast.cmds/shortcut/failed`, `replay.ran/commands/failed_at` (toplam 18). `main()` bunları `getattr(run, 'work', False)` ile geri okuyor.
- Globaller: `TURN` (dict), `STOPPING`, `_APPS_CACHE`, `MainMove.carried` (sınıf seviyesi sözlük).
- Parametre olarak ortam değişkeni: `replay()` `ATTICUS_REQUEST`'i geçici değiştirip geri alıyor (`1890-1922`), `menu_bar_click()` özyineleme koruması için `ATTICUS_BAR` yazıyor (`2954`), `main()` `ATTICUS_ASK/FRONT/HANDS_STATE/RELAY_OWNER/RELAY_ACTIVE` yazıyor. 29 farklı `ATTICUS_*` değişkeni, ~178 okuma.
- Neden önemli: Bu kod çok thread'li (relay thread, `MainMove.watch`, `threading.Timer` ile timeout, ajan okuma thread'leri). Paylaşılan global durum yarış koşullarına açık ve bir fonksiyonu başka modüle taşıdığınızda neyin neye bağlı olduğunu görmek imkânsız.
- Öneri: `RunResult`/`FastResult`/`ReplayResult` dataclass'ları döndürün; istek bağlamını (`ask_dir`, `front_app`, `request`, `is_agent`, `commit_path`…) bir `AskContext` nesnesinde toplayın. Ortam değişkenleri yalnızca **süreç sınırında** (alt süreç başlatırken) kullanılsın.

**M3 — Güvenlik politikası 7 kopya** · 🟠 Orta
- `DENIED/DENY` (`572`), `RISKY` (`585`), `RISKY_LABEL` (`594`, "Swift'teki riskyPattern ile aynı" yorumu), `UNSAFE` (`1641`), `RISKY_CLICK` (`2348`), `HANDS_RISK` (`2750`), ayrıca `action_kind()` içinde yorumlayıcı listesi (`4002-4004`). Hepsi farklı kelimeler/kurallar içeriyor.
- Öneri: Tek `policy.py`; Swift ile paylaşılan kelime listesi tek bir JSON kaynağından üretilsin; tablo-tabanlı tek test seti.

**M4 — Atomik dosya yazma 10+ farklı şekilde** · 🟢 Düşük
- `private_json` var ama `_save_profile`, `_save_memory_rules`, `save_skills`, `workflows`, `playlist`, `remember_background_tab`, `browser_adapter.remember`, `window_text`, `window_summary`, `routine_install` kendi versiyonlarını yazıyor (9× `NamedTemporaryFile`, ~25× `.tmp` + `os.replace`). Bazıları atomik değil: `tool_help` önbelleği (`6156`), `install_id` (`3373`), `Path(LAST).write_text` (`2135`).
- Öneri: `storage.py` içinde `atomic_write_json/text`, `append_jsonl`, `read_jsonl`, `file_lock` — tek implementasyon.

**M5 — Prompt'lar kodla iç içe; string ameliyatı** · 🟢 Düşük
- `system_prompt()` prompt cümlelerini `.replace('Work behind: never activate…', 'Work in front: …')` ile değiştiriyor (`4943`). Prompt metnindeki tek kelimelik değişiklik bu replace'i sessizce bozar. Ajan prompt'u da aynı şekilde parçaları `replace(main_only, '')` ile çıkararak üretiliyor (`4964`).
- Öneri: `prompts.py` içinde parçalardan açıkça birleştirme (`compose(work_in_front=…, agent=…)`).

**M6 — Python, ayar listesini HTML'i regex'le parse ederek öğreniyor** · 🟢 Düşük
- `switches()`/`picks()` `ui/settings.html`'i regex ile tarıyor (`875-888`). Settings sayfasındaki bir markup değişikliği AI'nin `--set` aracını bozar.
- Öneri: Ayar şeması tek bir JSON dosyasında; HTML ve Python ikisi de oradan okusun.

**M7 — Ölü / eski kod** · 🟢 Düşük
- Gumroad (P2), `SHOT` sabiti (yalnızca etiket için), `[done]` eski prompt uyumluluğu (`5398`), `ask()` diyalog yolu. `--selftest` modül globallerini (`SKILLS`, `ME_FILE`, `screens`, `show`, hatta `subprocess.run`) yeniden atıyor (`7587-7631`) — paket yapısında çalışmaz, `tests/`'e taşınmalı.

**M8 — Python sürümü/araçlar tanımsız** · 🟢 Düşük
- Walrus, `str.removeprefix` (3.9+) kullanılıyor; hangi `python3`'ün çalışacağı `PATH`'e bağlı ve satır 491 Homebrew'u başa ekliyor. Linter, formatter, tip kontrolü yok.
- Öneri: Minimum sürümü belgeleyin (macOS CLT ile gelen 3.9), `ruff` + `pyflakes` ekleyin.

### 4.3 Performance

**F1 — Her helper çağrısı tüm "beyni" yeniden yüklüyor** · 🟡 Orta · ölçüldü
- Bir istekte: `--wait` worker + her tool call için `--gate` hook süreci + AI'nin çağırdığı her helper (`--place`, `--hands`, `--web`, `--look` …) ayrı Python süreci. Her biri 480 KB kaynağı yüklüyor.
- Ölçüm: derleme ~**80 ms**/çağrı (önbelleksiz). Satır 1–2'deki `sh`+Python polyglot başlık, bytecode'u `~/Library/Caches/Atticus`'a önbellekleyip bu maliyeti atlamak için var (Python, doğrudan çalıştırılan script'i hiç önbelleklemez). Önbellekle bile stdlib importları (`urllib.request` tek başına ~20 ms) her `--gate` çağrısında ödeniyor.
- Öneri: Küçük bir giriş dosyası + paket. Python paketteki modülleri zaten önbellekler; polyglot hileye gerek kalmaz. `--gate` gibi sıcak yollar yalnızca ihtiyaç duyduğu modülleri import etsin (lazy import). **Dikkat:** `.pyc`'ler imzalı `.app` paketinin içine yazılmamalı (kod imzasını bozar) → `sys.pycache_prefix` ayarı giriş dosyasında korunmalı.

**F2 — Loglar sınırsız büyüyor ve tamamı okunuyor** · 🟡 Orta · ölçüldü
- `log.jsonl` yalnızca ekleniyor (her istek ~6 satır: başlangıç, adımlar, sonuç); hiç döndürülmüyor. `read_rows()` dosyanın tamamını parse ediyor: Settings penceresi (`--state`), `--budget`, `history()`, `ran_programs()` (CLI adı geçen her istekte `tool_help` üzerinden), `feedback()`.
- 1 yıl × 30 istek/gün simülasyonu (15,8 MB): `read_rows` **134 ms**, `history()` **155 ms**, `ran_programs()` **181 ms**; doğrusal büyüyor.
- Ajanlar: her Claude stream olayı ajanın `log.jsonl`'ine sonsuza kadar yazılıyor (`4675`); ajan klasörleri hiç silinmiyor (`4909` bilinçli); `agent_usage_rows()` Settings açıldığında **tüm ajanların tüm loglarını** okuyor (`6059`).
- Öneri: Boyut/tarih bazlı rotation; özet sayaçları (maliyet, süre) ayrı küçük bir dosyada tutun; ajan olay logunu sınırlayın veya özetleyin.

**F3 — Her AppleScript için yeni `osascript` süreci** · 🟡 Orta
- 76 `osa`/`osascript` çağrı noktası. `place()` tek pencere taşıması için 10–20 `osascript` süreci başlatabiliyor (her biri ~50–150 ms); `screens()` her çağrıda JXA süreci açıyor ve önbelleksiz (`place` içinde ve istek başında birkaç kez).
- Öneri: Swift tarafı zaten AX erişimine sahip (`--hands`, `--window-target`); pencere yerleştirme ve ekran listesi Swift'e taşınabilir ya da tek script'te toplanabilir; `screens()` süreç içinde önbelleklensin.

**F4 — `pref()` her çağrıda `settings.json`'u okuyup parse ediyor** · 🟢 Düşük
- 100 çağrı noktası; `system_prompt()` tek başına ~8 kez çağırıyor; `gate()` her tool call'da birkaç kez.
- Öneri: mtime kontrollü süreç-içi önbellek.

**F5 — Spotify playlist taraması tüm önbelleği okuyor** · 🟢 Düşük
- `playlist()` `~/Library/Application Support/Spotify` altındaki **her dosyayı** tamamen belleğe okuyor (`1375-1380`); Spotify önbelleği yüzlerce MB olabilir. Saatte en fazla bir kez, ama "play X" isteğinin sıcak yolunda. Ardından 16 paralel oEmbed isteği.
- Öneri: Yalnızca ilgili küçük dosyaları tarayın veya boyut sınırı koyun.

**F6 — Küçük ama sık tekrarlanan işler** · 🟢 Düşük
- `skills()` her çağrıda tüm kısayolları okuyup yeniden `shlex` ile normalize ediyor (konuşma sırasında "her kelimede" çağrılan yolda). `watch_connector()` 15 dakika boyunca 5 sn'de bir `claude mcp list` (Node CLI) başlatıyor (`4609-4617`).

### 4.4 Stability

**S1 — Polling tabanlı IPC** · 🟡 Orta
- `relay()` istek boyunca 20 ms'de bir `os.listdir` + `exists` (`5015-5063`); `ask_user()` 600 sn'ye kadar 20 ms polling; `wait_commit()` 90 sn'ye kadar 20 ms; ajan servisi 150 ms'de bir her ajan klasörünü tarıyor.
- Neden önemli: Pil/CPU uyanmaları, gecikme ve "dosya yarım yazıldı mı" gibi yarış koşulları (kod bunları `.tmp`+`rename` ile özenle çözmüş, ama karmaşıklığın kaynağı bu).
- Öneri: Stdlib'deki `select.kqueue` (macOS) ile dosya olaylarını bekleyin ya da Swift ↔ Python arasında zaten açık olan stdin/stdout kanalını kullanın.

**S2 — Thread'ler arası korumasız paylaşılan durum** · 🟡 Orta (olası, doğrulanmadı)
- `run()` içindeki `threading.Timer` (`expire`) `end_turn()` → `TURN` güncellemesi yapıyor; aynı anda ana thread `TURN['step_times']`'ı değiştiriyor; kilit yok. `run.*` attribute'ları da birden fazla thread'den yazılıyor.
- Öneri: M2'deki `Turn` nesnesi + kilit.

**S3 — Dağınık süreç yaşam döngüsü** · 🟡 Orta
- 13 farklı `signal.signal` çağrısı; `start_claude`, `run_devin`, `run_pi`, `meeting_call`, `meeting_live`, `dictate_cleanup_wait` her biri SIGTERM handler'ını üzerine yazıyor. `stop_workers` sinyal handler'ı içinden dosya yazıyor, `posthog` süreci başlatıyor ve `sys.exit` çağırıyor (`3788-3795`) — kod herhangi bir noktada (kilit içinde, `finally` ortasında) kesilebilir. 22 `atexit.register`.
- Öneri: Tek bir `lifecycle` sahibi: alt süreçleri bir registry'de tutsun, SIGTERM'de sırayla kapatsın.

**S4 — Sessizce yutulan hatalar** · 🟢 Düşük
- Çok sayıda `except (OSError, ValueError): pass`; 13 adet `except Exception`. Telemetri çökmeleri yakalıyor ama sessiz başarısızlıklar (ör. `routine_repair`, `tool_help` önbellek yazımı) görünmez.
- Öneri: En azından debug log'a yazın.

**Güçlü yönler** (refactor'da korunmalı): neredeyse her alt süreçte timeout; atomik yazma + `0600` izin disiplini; `flock` kullanımı; model çıktısının sıkı doğrulanması (`drawing()`, `parse_handoff()`); telemetrideki gizlilik temizleme (`clean()`); 75 dosyalık test seti.

---

## 5. `Atticus.swift` bulguları

Swift dosyası ayrı bir inceleme ile baştan sona okundu. 🔴/🟠 bulguların kodu tarafımdan tekrar kontrol edildi. "Olası" işaretli olanlar kod okumasına dayanıyor, çalıştırılarak doğrulanmadı.

### 5.1 Yapı

- 7.324 satır, tek modül, `main.swift` (script) modunda top-level kodla çalışıyor. Aynı binary hem menü çubuğu uygulaması hem de Python'un çağırdığı CLI (`--hands`, `--look`, `--calendar`, `--type`, `--window-target` …).
- En büyük parçalar:
  - `final class App` (overlay denetleyicisi): **1.585 satır, ~120 stored property**, 10 farklı yere dağılmış.
  - `enum Hands` (AX/Quartz otomasyon motoru + CLI): ~1.300 satır, fiilen ayrı bir program.
  - `MeetingCopilot`: ~640 satır, ~65 property.
  - `AgentPanels`: ~500 satır.
  - `SettingsWindow`: ~350 satır.
- 13 top-level `var` (~20 değişken), ~12 singleton (`app`, `agentsUI`, `meeting`, `settings`, `onboarding`, `bar`, `calendar` …), ~17 `static var`. Her sınıf diğer singleton'lara doğrudan erişiyor.
- Stringly-typed: 63 farklı ayar anahtarı 222 yerde; tüm köprü mesajları `[String: Any]`.
- `Prefs.retiredKeys` hiç kullanılmıyor ama "emekli" ayarlar varsayılan değerleriyle hâlâ davranışı yönetiyor.

### 5.2 Stabilite

| # | Önem | Bulgu | Yer |
|---|---|---|---|
| SW-S1 | 🔴 Yüksek · teyit edildi | **Settings'te pipe deadlock.** `--state` çağrısı önce `waitUntilExit()`, sonra pipe'ı okuyor. Python'un JSON'u (son 50 isteğin tam cevapları + kurallar + kısayollar + profil) pipe tamponunu (16–64 KB) aşınca ikisi de birbirini sonsuza kadar bekler. Sonuç: Settings'te kullanım/geçmiş görünmez, her `refresh()`'te bir Python süreci ve bir GCD thread'i sızar. Aynı sıra `--check`, `--connectors` ve `Updater.sh`'de de var (çıktıları şimdilik küçük). | `4589-4596`, `3908`, `4024`, `4282` |
| SW-S2 | 🔴 Yüksek · teyit edildi | **`Prefs.d` veri yarışı.** Kilitsiz global `static var` sözlük ana thread'de yazılıyor (`Prefs.set`, pencere boyutlandırırken `Prefs.d["boxW"] = …`). Aynı anda `Onboarding.perms()` her 1,5 sn'de `DispatchQueue.global()` üzerinden okuyor. Swift'te sözlük okunurken yazılması tanımsız davranış; ara sıra çökme üretir ve tam da kullanıcının ayar değiştirdiği anda tetiklenir. | `202-225`, `3898-3903`, `4562-4566` |
| SW-S3 | 🟠 Orta | Mikrofon buffer callback'i `Mic.queue` üzerinde `speechInputs`'u okurken ana thread onu yeniden atıyor. | `2648-2664` |
| SW-S4 | 🟠 Orta · olası | `spawn()` içinde `readabilityHandler` ve `terminationHandler` aynı FileHandle'ı eşzamanlı okuyabiliyor; satırlar sırasız gelip son `✓` satırı bölünebilir. | `3250-3253` |
| SW-S5 | 🟠 Orta | Hands özel API'ler kullanıyor: SkyLight, `GetProcessForPID`, belgelenmemiş CGEvent alanları ve sabit ofsetten ham bellek okuma (`load(fromByteOffset: 24…)`). Bir macOS güncellemesinde çökme ya da yanlış girdi riski var. | `6316-6362` |
| SW-S6 | 🟠 Orta | **Kayıp ayar güncellemeleri.** Swift `settings.json`'u bir kez okuyup her `set`'te tamamını yeniden yazıyor ve dosyayı hiç yeniden okumuyor. Python'un `save_pref` ile yazdığı değer Swift'in bir sonraki yazımında sessizce geri alınır. | `202-225`; py `401-407` |
| SW-S7 | 🟢 Düşük | `NSScreen.main!` ve `NSScreen.screens[…]` ekran yokken (kapak kapalı, ekran yeniden yapılandırılırken) çöker. | `595`, `3371`, `4135`, `5179` |
| SW-S8 | 🟢 Düşük | 150 adet `try?`. Onay dosyası yazımı başarısız olursa Python'un gate'i sessizce bekler. | `2171`, `2304`, `2314` |
| SW-S9 | 🟢 Düşük | Ajan servisi ve toplantı yardımcısının stdin'ine ana thread'den yazılıyor. Pipe dolarsa bütün uygulama donar. | `3382-3387`, `5560` |

İyi durumda olanlar: timer closure'ları `[weak self]` kullanıyor; monitor'ler temizleniyor; `spawn()`'daki Process/Pipe sızmıyor (50 süreçle denenip doğrulandı); UI işi tutarlı olarak ana thread'e dönüyor.

### 5.3 Performans

| # | Önem | Bulgu | Yer |
|---|---|---|---|
| SW-P1 | 🔴 Yüksek | Ekrana çizilen rehberlerde her adımın hedefi **ana thread'de** AX ile çözülüyor. Her adımda ~2 sn'ye kadar donma oluyor ve Esc/hotkey gecikiyor. | `1367-1372`, `1967`, `6149-6163` |
| SW-P2 | 🟠 Orta | `finishPoint` ana thread'de `screencapture` çalıştırıp bitmesini bekliyor. | `1925-1928` |
| SW-P3 | 🟠 Orta | Menü çubuğu her açıldığında ana thread'de **tüm `log.jsonl`'i** ve her ajanın `state.json`'unu okuyor (Python'daki F2 ile aynı sınırsız dosya). | `4383-4400` |
| SW-P4 | 🟠 Orta | Onboarding penceresi açıkken: 20 Hz JS, saniyede bir izin kontrolü (Apple Events probu 1,5 sn bekleyebilir), 5 sn'de bir `--check`. | `3874-3880` |
| SW-P5 | 🟠 Orta | Settings penceresi: 1,5 sn'lik polling; her değişiklikte uygulama ikonu yeniden base64 PNG'ye çevriliyor; ilk açılışta ana thread'de `git log`. | `4563-4587`, `4289` |
| SW-P6 | 🟠 Orta | Her dinleme başlangıcında ana thread'de `skills.json`/`me.json` okunuyor ve dört uygulama klasörü listeleniyor. | `1837-1845` |
| SW-P7 | 🟠 Orta | Ana thread'de AX polling: metin seçimi yakalama, mini ekran (0,5 sn), düzeltme timer'ı (0,35 sn, 20 sn boyunca). | `2027`, `1577-1618`, `2865` |
| SW-P8 | 🟠 Orta | Toplantı yardımcısı her soruda tüm transkripti gönderiyor; uzun toplantıda gönderilen veri karesel (O(n²)) büyüyor. Bu yazım ana thread'de senkron. | `5431-5442`, `5560` |
| SW-P9 | 🟢 Düşük | Boşta uyanmalar: 10 Hz ajan paneli (ajan satırı varken sürekli), 1 Hz mikrofon kontrolü, 2 sn ses kurtarma taraması, 3 global keyDown monitor'ü. | `3353`, `7207`, `435` |

### 5.4 Güvenlik

| # | Önem | Bulgu | Yer |
|---|---|---|---|
| SW-SEC1 | 🟠 Orta | **WebView köprüsü her script'e güveniyor.** Hiçbir sayfada CSP yok; mesaj handler'ları tüm frame'lere açık; overlay/ajan/toplantı/onboarding webview'larında navigasyon politikası yok. Overlay'de çalışan herhangi bir script `{allow:true}` göndererek **safe-mode onay kartını kendi kendine onaylayabilir** veya `{send:…}` ile yeni istek başlatabilir. `agents.html`'den gelen bilinmeyen aksiyonlar doğrudan Python servisine iletiliyor. Sayfalara güvenilmeyen HTML girip girmediği §6'da incelendi. | `1976-2177`, `3809` |
| SW-SEC2 | 🟢 Düşük | Python'dan gelen `⚙` satırı her String ayarı (ör. `apiBase`, `apiKey`, `client`) değiştirebiliyor. Python'un kendi kuralı bunları yasaklıyor; Swift aynı izin listesini uygulamalı. | `3210-3214` |
| SW-SEC3 | 🟢 Düşük | `--state` çıktısı JS kaynağı olarak `evaluateJavaScript`'e veriliyor; ajan id'si JS string'ine gömülüyor. | `4594`, `3516` |
| SW-SEC4 | 🟢 Düşük · olası | Ajan çıktısındaki bağlantı/dosya `NSWorkspace.open` ile açılıyor; ajanın ürettiği bir `.command`/`.app` tıklanınca çalışır. | `3753-3760` |
| SW-SEC5 | 🟢 Düşük | API anahtarı `settings.json`'da düz metin. `.atomic` yazım önce varsayılan umask (0644) ile oluşturup sonra 0600 yapıyor. Keychain tercih edilmeli. | `217-223` |

### 5.5 Bakım

- En uzun fonksiyonlar: `Hands.cli` 143 · `App.init` 135 · `SettingsWindow.handle` 104 · `App.spawn` 101 (Python satır protokolü inline) · `App.start(dictate:)` 99.
- 1.468 satır >120 karakter, 141 satır >200.
- Tekrarlar:
  - "Python'u çalıştır, stdout'tan JSON oku" ~13 kez, tutarsız bekleme/okuma sırasıyla (SW-S1'in kaynağı).
  - Satır okuyucu 4 kez.
  - Pano kaydet/geri yükle 3 kez.
  - İzin polling timer'ı 2 kez.
- Sihirli sayılar: Carbon hotkey ID'leri 1–7 altı farklı yere dağılmış; ham tuş kodları; 45 `asyncAfter`, 28 `usleep`.
- 35 test dosyası `Atticus.swift` kaynağını metin olarak dilimliyor veya derliyor (§6).

## 6. Testler, UI, build ve CI

### 6.1 Test paketi — çalıştırma sonuçları

| Çalıştırma | Test | Geçen | Başarısız | Atlanan | Süre |
|---|---|---|---|---|---|
| Orijinal yol, Python 3.14.6 | 815 | ~647 | 18 + 1 hata (15 metot) | 153 | 234 sn |
| Boşluksuz bir yola kopya, Python 3.14.6 | 815 | 657 | 5 | 153 | 223 sn |
| Aynı kopya, Apple Python 3.9.6 | 815 | 657 | aynı 5 | 153 | 267 sn |

**Başarısızlıkların hepsi ortamdan kaynaklanıyor**, ürün regresyonu değil:

- **14 tanesi:** "Personal Projects" klasör adındaki boşluk. Testler yolu shell string'ine tırnaksız koyuyor.
- **4 tanesi:** Prompt bütçesi testleri checkout yolunun ve home klasörünün uzunluğuna bağlı. Yol ~100 karakteri aşınca 10.000 karakter sınırını geçiyor. Bu, README'deki "repo'yu istediğiniz yere klonlayın" ifadesiyle çelişiyor.
- **1 tanesi:** Shell'inizdeki `PYTHONDONTWRITEBYTECODE=1` teste sızıyor.

Bu grupta bir küçük ürün hatası da var: `--selftest`, script boşluk içeren bir yoldayken başarısız oluyor (`7617`). Kurulu uygulamanın yolunda boşluk olmadığı için önemi düşük.

İn-process satır kapsamı (coverage) **%83,9** (5.730 satırın 4.807'si). 21 fonksiyon hiç çalışmıyor.

Asıl boşluk macOS köprüsü. osascript, AX, WebKit ve Chrome her yerde mock'lanıyor; gerçekte yalnızca VM'de çalışan 153 testte deneniyor. O VM'in çalıştırıcısı (`run.sh`) repoda yok, CI da hiçbirini çalıştırmıyor.

### 6.2 Testlerin `atticus.py`'ye bağımlılığı (refactor için belirleyici)

- Testler `atticus` modülünün **306 farklı özelliğine** dokunuyor.
- **120 farklı isim 1.245 yerde** monkeypatch ediliyor. En çok patch'lenenler: `pref` 66, `osa` 65, `wait_commit` 47, `preview_app` 41, `ask_user` 40, `say` 40, `DIR` 38.
- 57 test `atticus.main()`'i süreç içinde çalıştırıyor. Bunların hepsi geniş patch setlerine dayanıyor.
- **Neden kritik:** Bu 120 ismin 119'u `atticus.py` içindeki başka kodlar tarafından çağrılıyor. Patch bugün çalışıyor, çünkü çağıran kod ismi aynı modülün global'lerinden çağrı anında buluyor.
  - `pref`, `prefs.py`'ye taşınıp `from .prefs import pref` ile alınırsa testteki `patch.object(atticus, 'pref', …)` hiçbir şeyi değiştirmez.
  - Bu durumda testler sessizce gerçek koda düşer. Bazıları gerçek `osascript`'i, hatta kullanıcının hesabıyla **gerçek `claude`**'u başlatabilir. Test paketinde AI istemcilerini engelleyen bir koruma yok.
- **Kırılgan kaynak metni testleri:** 816 test metodunun **212'si** proje kaynağını metin olarak okuyor.
  - 113'ü yalnızca grep yapıyor.
  - 85'i kaynaktan işaretçi string'ler arasında kod kesip derliyor veya çalıştırıyor. Toplam 563 dilimleme noktası var; çoğu `Atticus.swift` ve `ui/*.html` üzerinde.
  - Python tarafında `test_atticus.py:474` `main()`'den iki kod satırı arasını kesiyor.
  - `test_ui_review_fixes.py:169` bir `assertNotIn` kontrolü. Kod taşınınca sessizce geçmeye devam eder ve koruma kaybolur.
- **İzolasyon import sırasına bağlı:** Bir test dosyası tek başına çalıştırılırsa (`-p test_feedback.py`) `DIR` gerçek `~/.config/atticus`'a, PostHog anahtarı da canlı anahtara düşüyor. 🟠 Orta.
- DIR'den türetilen 9 sabit (`MEMORY`, `RECENT`, `PREFS`, `SKILLS` …) modül yüklenirken hesaplanıyor. Testlerin `DIR` patch'i bunları değiştirmiyor; yazımlar ortak bir klasöre gidiyor.

### 6.3 UI

| Dosya | Boyut | İçerik |
|---|---|---|
| `ui.html` | 104 KB | %57 JS, %39 CSS |
| `settings.html` | 89 KB | Klasik `<script>`, bütün fonksiyonlar global |
| `onboarding.html` | 87 KB | — |
| `agents.html` | 68 KB | — |
| `meeting.html` | 44 KB | — |

- **XSS durumu iyi:**
  - AI cevapları DOM'u adım adım kuran bir markdown renderer ve `textContent` ile gösteriliyor.
  - Linkler yakalanıyor ve Swift yalnızca http, https ve mailto'ya izin veriyor; `javascript:` linkleri çalışamaz.
  - Kaçışsız birkaç küçük nokta var, ama veri yerel kaynaklardan geliyor: `settings.html:594-595`, `810-811`.
  - Eksik olan derinlemesine savunma: hiçbir sayfada CSP yok, oysa her sayfa ayrıcalıklı köprüye mesaj gönderebiliyor (bkz. SW-SEC1).
- **Performans** (olası):
  - `ui.html:580-603`: Akan cevabın her parçasında tüm cevap yeniden markdown'a çevriliyor ve her kelime span'e sarılıyor. Uzun cevapta maliyet karesel (O(n²)) büyüyor.
  - `fit()` her çağrıda layout okumaya zorluyor ve köprüye mesaj gönderiyor; 63 yerden, bazıları her frame'de çağrılıyor.
  - Settings her aksiyonda her şeyi `innerHTML` ile yeniden çiziyor; başka bir alana yarım yazılmış metin kaybolabiliyor.
- Kod tekrarı az. Yardımcılar (`$`, `capsOf`, `apiCost`, segmentli buton bağlama) sayfa başına yeniden yazılmış.
- Orb animasyonları gizliyken de saniyede ~4 kez uyanıyor (olası).

### 6.4 Build, CI ve paketleme

| Önem | Bulgu | Yer |
|---|---|---|
| 🔴 Yüksek | **İmzasız otomatik güncelleme.** Varsayılan açık; 6 saatte bir `main`'i `git pull` edip `./build.sh` çalıştırıyor. İmzalı tag ya da commit doğrulaması yok, kurulum da `curl \| bash`. `main`'e giren her commit (veya ele geçirilmiş bir hesap) 6 saat içinde Accessibility, Ekran Kaydı, Otomasyon ve mikrofon izni olan her kullanıcıya ulaşır. → Rabik'in `.dmg` modelinde bu güncelleyici kapalı (bkz. `docs/NOTARIZATION.md`). | `Atticus.swift:4296-4327`; `install.sh` |
| 🟠 Orta | CI yalnızca ubuntu'da çalışıyor. Swift hiç derlenmiyor ya da tip kontrol edilmiyor; macOS testlerinin hepsi atlanıyor. `nix.yml` yalnızca bir shell sarmalayıcıyı derliyor. | `.github/workflows/` |
| 🟠 Orta | Python sürümü sabitlenmemiş. Uygulama Mac'te hangi `python3` varsa (Apple 3.9.6 veya Homebrew) onunla çalışıyor; CI yalnızca ubuntu'nun varsayılanını deniyor. | `checks.yml` |
| 🟠 Orta · olası | Yerel imza anahtarı `-T /usr/bin/codesign` ile içe aktarılıyor. Herhangi bir süreç "Atticus Local Signing" kimliğiyle imza atabilir ve uygulamanın gizlilik izinlerini devralabilir. Hardened runtime de yok. | `build.sh:44-54` |
| 🟢 Düşük | `install.sh`, `ATTICUS_DIR`'i kaynak klasörü olarak kullanıyor; Python ise aynı değişkeni config klasörü ve "test sandbox'ı" olarak yorumluyor. Bu, telemetriyi ve güncellemeleri kapatıyor. | `install.sh:6`; py `37`, `3366` |
| 🟢 Düşük | `app.err` hiç döndürülmüyor; `checks.yml` action'ları SHA'ya sabitlemiyor; lint ve tip kontrolü yok. | `build.sh`, `checks.yml` |

`atticus.py` yalnızca standart kütüphaneyi kullanıyor (doğrulandı), yani bağımlılık manifestine gerek yok.

---

## 7. Önerilen yapı

### 7.1 Python

> Rename sonrası isimlerle (`rabik.py`). Giriş dosyasının adı ve yolu dış sözleşme olduğu için (§2) **aynı kalır**. Paket aynı klasörde ama farklı bir isimle durur: `rabik/` adında bir paket `import rabik`'te script'in önüne geçer.

Faz 4'ten sonra yapı bu (öneri hâline göre farklar: `show` ile `web()` birbirini çağırdığı için ikisi `web.py`'de; `context` ve
`handoff` modülleri `main()`/`run()` içindeki aynı adlı yerellerle çakışmasın diye `situation` ve `handoffs`; `routine`, `watcher`,
`support` adları da dışa açılan fonksiyonlarla çakışmasın diye seçildi):

```
rabik.py            ← giriş script'i + uyumluluk cephesi (~170 satır, çoğu --selftest)
                       • sys.pycache_prefix = ~/Library/Caches/Rabik (imzalı .app'e .pyc yazılmaz)
                       • ME = bu dosyanın yolu (helper komutları, gate, kaydedilmiş kısayollar buna bağlı)
                       • her modülün __all__'ını düz isim olarak açar, yazmaları sahibine iletir; _LIVE global'lerini canlı okur
                       • PATH ve alt katmanların yukarı çağırdığı iki kanca (protocol → clients.stop_workers, turn → skills.replay)
brain/              (bağımlılıklar önce)
  paths.py          HOME, DIR, ME, APP, helper komutları; DIR'den türetilen yollar (request_file, hands_state, LAST, WORKED)
  wording.py        konuşulan isteği eşleme: plain, norm, gist, STOP/FILLER, DEICTIC, dictate_sound (fonetik anahtar)
  protocol.py       stdout etiketleri (· ▸ ✓ ! ? ◇ ⤴ ⇢ ▣ @ ✎ ↺ ⚙ ▤ i …) + say, emit
  labels.py         kutudaki adım etiketleri (label)
  storage.py · prefs.py · telemetry.py · prompts.py · turn.py
  toolhelp.py       kullanıcının kendi CLI'larının yardımı (yol + mtime ile önbellekli)
  memory.py         profil (About you), kurallar, recent, history
  situation.py      isteğin kelimeler dışındaki bağlamı: seçim, işaret, çizim, devam edilen tur
  messages.py       modele giden istek blokları ve akıştan gelen içerik blokları
  macos.py          osa, screens, front, odak koruma, iş penceresi önizlemesi (▣)
  apps.py           kurulu/çalışan uygulamalar, adlar, quit_app, app_up
  interaction.py    ask_user, relay, pick, set_switch, need, seçim kartı
  windows.py        place, place_many, move_target
  policy.py         risk tabloları, risky(), gate(), action_kind(), ajan URL izin listesi  ← tek güvenlik kaynağı
  hands.py          hands_call/action/map, menü çubuğu
  web.py            get, search, show + arka plan sekmeleri, web(), page_ready
  screen.py · drawing.py · spotify.py · calendar.py · routine.py · watcher.py · support.py · meeting.py · dictation.py
  skills.py         öğrenilmiş kısayollar, replay, workflow'lar
  clients.py        plan(), start_claude, Devin/Pi ayarları, stop_claude, stop_workers
  handoffs.py       direktifler, isimli ajanlar, MainMove
  agents.py         ajan yardımcıları + Agents servisi
  ask.py            run(), run_devin, run_pi
  tips.py · instant.py (fast)
  cli.py            main(): bayrak dağıtımı + istek orkestrasyonu
```

**Bağımlılık yönü:** döngü yok; `tests/test_brain.py` her modülün `from brain import …` satırlarından grafiği kurup döngüyü
reddediyor. Gerçek sıra `rabik.py`'deki `_MODULES` listesinde.

**Kurallar:**

1. Modüller birbirini **modül adıyla** çağırır (`prefs.pref()`), `from .prefs import pref` ile değil. Böylece testlerdeki patch'ler çalışmaya devam eder.
2. Standart kütüphane modül olarak kullanılır (`subprocess.run(...)`). Testlerdeki 321 stdlib patch'i buna dayanıyor.
3. Fonksiyon attribute'u ile dönüş yok: `RunResult`, `FastResult` ve `ReplayResult` dataclass'ları kullanılır.
4. `os.environ` yalnızca süreç sınırında okunur ya da yazılır. Süreç içinde `AskContext` nesnesi taşınır.

1 ve 2 Faz 2–4'te, 3 Faz 5b'de, 4 Faz 5c'de uygulandı (4: tek sahip `brain/environ.py`; değerler canlı okunuyor, çünkü ortam alt süreçlere giden kanal).

### 7.2 Swift

`Sources/Rabik/` altında tek modül, `swiftc -wmo -module-name Rabik` ile derlenir.

```
main.swift          yalnızca açılış: AudioRecovery, CLI dağıtımı, kilit, singleton'lar, timer'lar, hotkey kaydı
Core/               Prefs (kilitli), Paths, PythonBridge (runJSON: önce oku, sonra bekle + LineReader), WebBridge, AX, Panels
Audio/ Speech/ Hotkeys/ Dictation/ Text/
Overlay/            App.swift (tüm stored property'ler) + App+Bridge, App+Listening, App+Worker (typed WorkerLine), App+Pointing
Drawing/ MiniScreen/ Agents/ Onboarding/ Settings/ App/(MenuBar, Delegate, Updater) Meeting/
Hands/              Model, AX, Menu, Input, Scroll, Text, CLI, Selftest
CLI/                --look, --text, --raise, --calendar, --window-target, --type
```

Swift agent'ının doğruladığı tuzaklar:

1. `-module-name` verilmezse birden fazla dosyada modül adı `main` olur ve `Atticus.settings` (rename sonrası `Rabik.settings`) referansları derlenmez.
2. Yan etkili global'ler `main.swift` dışına taşınırsa tembel başlatılır. Örneğin ⌃⌘V kısayolu kendi başlatıcısında kaydediliyor; başka dosyada ancak ilk okunduğunda kaydedilir.
3. Extension'lar stored property tutamaz. Önce `App`'in property'leri tek yerde toplanmalı.
4. SwiftPM'e geçilirse Swift 5 dil modu seçilmeli; Swift 6 modu mevcut global'leri reddeder.

---

## 8. Geçiş planı

Her fazın sonunda şunlar çalıştırılır: unit testler (boşluksuz bir yolda), `--selftest`, `swiftc -typecheck` ve Mac üzerinde gerçek bir istekle kısa bir smoke test. Her faz ayrı commit.

| Faz | İş | Boyut |
|---|---|---|
| **0 — Güvenlik ağı** | (a) git başlangıç commit'i ✅ · (b) Rabik rename (devam ediyor) · (c) Testler: `tests/__init__`'te sahte `claude/devin/pi` (çağrılırsa yüksek sesle başarısız olur), host guard'a `claude` ve `screencapture` eklenir, config izolasyonu import sırasından bağımsız hale gelir, prompt bütçesi testleri yol uzunluğundan bağımsız olur · (d) CI'a macOS runner + `swiftc -typecheck` + Python 3.9 matrisi | M |
| **1 — Acil düzeltmeler** | P1 (gate: `QUIET` öncesi yönlendirme kontrolü, yorumlayıcılar her zaman sorulur; ileride ana istekleri de sandbox'ta çalıştırmak) · P2 (Gumroad kodunu silmek) · SW-S1 (`runJSON`: önce oku, sonra bekle) · SW-S2 (`Prefs` kilidi veya yalnızca ana thread) · SW-SEC1 (navigasyon politikası, `isMainFrame` kontrolü, CSP) | S–M |
| **2 — Python iskeleti** | `rabik.py` cephesi + `brain/paths, prefs, storage, protocol, telemetry, prompts`. Davranış değişikliği yok; testler değişmeden geçmeli. | M |
| **3 — Python alanları** | memory, routine, watcher, support (feedback), meeting, dictation + dayandıkları temel: wording, macos (`osa`), clients (`stop_claude`), turn | M |
| **4 — Python çekirdeği** | policy, interaction, macos, windows, apps, hands, screen, web, clients, handoff, agents, ask, cli; çekirdeğe bağlı alanlar: calendar, drawing, spotify, skills, instant | L |
| **5 — Gizli akışı temizleme** | `RunResult`/`FastResult`/`ReplayResult`, `AskContext`, `Turn` sınıfı, tek sinyal/süreç sahibi; testleri `patch.object(brain.<modül>, …)` biçimine codemod ile taşıyıp cepheyi inceltmek | L |
| **6 — Swift bölme** | Faz 0: `Sources/Rabik/main.swift` + `build.sh` + test yardımcıları (`native_source()`, `native_build()`) → yaprak yardımcılar → bağımsız özellikler (Hands, Drawing, MiniScreen, Meeting) → denetleyiciler → CLI → `App`'in bölünmesi | L |
| **7 — Performans** | Log rotation; Python tarafında `screens`/`pref` önbelleği ve `place()`'in Swift'e taşınması; polling yerine kqueue/stdin; Swift tarafında AX ve süreç işlerinin ana thread'den alınması | M |

Faz 2–5 Python, Faz 6 Swift üzerinde. Aynı dosyalara dokunmadıkları için paralel yürüyebilirler. Faz 0 ve 1 ikisinden önce gelmeli.

---

## 9. Durum

| Faz | Durum | Ne yapıldı |
|---|---|---|
| 0 — Güvenlik ağı | ✅ | Testler gerçek `claude`/`devin`/`pi`'yi başlatırsa yüksek sesle başarısız oluyor (`RealClientLaunched` + son çalışan `test_zz_host_guard`); `screencapture` host guard'da. Her test modülü `tests`'i `rabik`'ten önce import ediyor (tek dosya koşusunda da izole) ve bunu bir test denetliyor. Prompt bütçeleri sabit bir kurulum yoluyla ölçülüyor; testler ve `--selftest` boşluklu yolda (bu klasör) da geçiyor; bytecode testi geliştiricinin `PYTHONDONTWRITEBYTECODE`'unu yok sayıyor. CI: Ubuntu Python 3.9 + 3.13 ve macOS-26 (Swift derleme dahil), action'lar SHA'ya sabit. |
| 1 — Acil düzeltmeler | ✅ (SW-SEC1 hariç) | **P1:** yönlendirme kontrolü sessiz helper'lardan önce; yorumlayıcılar (python/perl/node/sh -c/eval…), dosya değiştiren programlar (cp, truncate, sed -i, wget…), yıkıcı git ve sistem komutları program konumunda yakalanıyor — `$(…)`, backtick, `find -exec`, `xargs`, `env` içinde de; `tests/test_gate.py` 23 atlatma + 12 normal komut. **P2:** Gumroad kodu silindi. **SW-S1:** dört çağrı önce okuyup sonra bekliyor; kaynak testi eski dört satırı yakalıyor. **SW-S2:** `Prefs.d` `NSLock` arkasında; ThreadSanitizer altında eski kod çöktü (SEGV), yeni kod temiz. |
| 2 — Python iskeleti | ✅ | `brain/` paketi: `paths`, `storage`, `prefs`, `protocol`, `telemetry`, `prompts` (~580 satır `rabik.py`'den taşındı, kod değişmeden). `rabik.py` giriş script'i ve uyumluluk cephesi olarak kaldı: taşınan isimleri yeniden dışa açıyor ve `patch.object(rabik, …)` yazmalarını sahibi olan modüle iletiyor. Eşdeğerlik ölçüldü: 115 sabit ve 321 fonksiyon imzası aynı, `system_prompt()` 2.048 ayar kombinasyonunda birebir aynı. `ME` hâlâ `rabik.py`; `python3 rabik.py` ile başlatılsa bile `brain/` bytecode'u imzalı paketin içine yazılmıyor. `build.sh`, `flake.nix` ve testler `brain/`'i de kopyalıyor. |
| 3 — Python alanları | ✅ (6/11) | `memory`, `routine`, `watcher`, `support` (geri bildirim), `meeting`, `dictation` ve dayandıkları temel katman `wording` (metin eşleme), `macos` (`osa`), `clients` (`stop_claude`), `turn` (TURN, checkpoint, log_turn) `brain/`'e taşındı; istek dosyası yolları (`request_file` …) `paths`'e eklendi (~1.300 satır, kod değişmeden). Modül adları `routines`/`watch`/`feedback` fonksiyonlarıyla çakışmasın diye §7'dekinden farklı. `STOPPING` iptalde yeniden bağlandığı için cephede kopyası yok: `turn.STOPPING` okunuyor. `log_turn` skills'teki `replay.ran`'a `turn.replayed` kancasıyla ulaşıyor. Taşıma betiği kapsam farkında (symtable): `text`/`turn` adlı yereller dokunulmadan kaldı. Eşdeğerlik ölçüldü: 444 üst düzey tanım (Faz 2 modülleri dahil) yeniden yazımlar geri alınınca AST olarak birebir aynı; cephede 446 isim aynı tür, imza ve değerde (yalnızca `STOPPING` çıktı); hiçbir fonksiyon tanımsız bir global okumuyor. Bulunan tek davranış farkı düzeltildi: `--selftest` `ME_FILE`'ı modül seviyesinde yeniden bağlıyordu, bu artık `brain.memory`'ye ulaşmadığı için selftest gerçek profile yazacaktı. Şimdi `memory.ME_FILE`, ve `tests/test_brain.py` böyle bir modül seviyesi atamayı yakalıyor (Faz 4'te `SKILLS`, `screens`, `show` taşınınca da). Kaynak metne bakan iki test (`test_onboarding_copy`, Gumroad kontrolü) artık `brain/`'i de okuyor. **Ertelenenler:** `calendar`, `drawing`, `spotify`, `skills`, `instant` çekirdeğe (`ask_user`, `need`, `wait_commit`, `hands_*`, `screens`, `emit`, `risky`, `show`, `place_*` …) bağlı; `brain` `rabik`'i import edemediği için bu katmanlarla birlikte Faz 4'te taşınacaklar. |
| 4 — Python çekirdeği | ✅ | `rabik.py`'de kalan ~5.100 satır 21 yeni modüle taşındı (apps, situation, interaction, labels, policy, hands, windows, web, drawing, screen, spotify, skills, messages, calendar, toolhelp, handoffs, agents, ask, tips, instant, cli); `paths`, `protocol`, `macos`, `clients` büyüdü. Faz 3'ün ertelediği beş alan da bunlarla taşındı. `rabik.py` artık yalnızca giriş script'i: cephe, `PATH`, iki kanca ve `__main__` (selftest), ~170 satır. Fonksiyon düzeyinde yalnızca üç küçük karşılıklı özyineleme vardı (`run`↔`run_devin`/`run_pi`, `show`↔`web()`, `hands`↔`menu_bar_click`), her biri tek modülde. Yanlış katmandaki birkaç küçük yardımcı yerine alındı (`WORKED`/`LAST`/`hands_state` → paths, `emit` → protocol, `managed_agent` ve ajan URL yardımcıları → policy, `preview_app` → macos, `need` → interaction, `dictate_sound` → wording) ve modül grafiği döngüsüz. Cephe her modülün `__all__`'ını programla açıyor; `STOPPING` ve `_APPS_CACHE` kopyalanmıyor, `_LIVE` ile sahibinde okunup yazılıyor (`patch.object(rabik, '_APPS_CACHE', …)` dahil). Taşıma betiği kapsamı symtable ile tam izliyor (aynı satırdaki lambdalar, inline comprehension'lar); bir yerelin modül adını gölgelediği 4 yerde `brain.paths.HOME` gibi paket yolu kullanılıyor. Selftest'in sahteleri (`installed_apps`, `SKILLS`, `screens`, `show`, `ME_FILE`) sahibine yazıyor. **Eşdeğerlik:** Faz 3'e göre 445 üst düzey tanım AST olarak aynı; cephede 446 isim aynı tür, imza ve değerde (`STOPPING` yine okunabilir); tanımsız global yok. **Testler:** Python 3.14 ve Apple 3.9 (boşluklu yol) tam paket geçti; selftest geçti ve profile yazmıyor; `--gate` başlangıcı 66 → 68 ms. İmzalı release build tüm modülleri taşıyor; paketteki helper çalışıyor, pakete bytecode yazmıyor, imza geçerli kalıyor. |
| 5 — Gizli akışı temizleme | ✅ | **5a ✅** Unit testler cepheden sahip modüle taşındı: 32 dosyada ~2.200 `rabik.X` referansı ve 829 `patch.object(rabik, …)` bir codemod ile `brain.<sahip>.X` oldu (kapsamı symtable ile izliyor; fonksiyon içi `import rabik`'ler de). Birden çok modülün isimlerini patch'leyen 28 `patch.multiple(rabik, …)` sahip başına bölündü ve `tests.patches(…)` ile birleşiyor. Cephe yalnızca eval harness (eski checkout'lara karşı da çalışıyor), alt süreç script'leri ve selftest için kaldı; `_LIVE` ve `__getattr__`/`__delattr__` çıktı. `test_brain` artık hiçbir unit testin cepheyi kullanmadığını denetliyor. Tam paket 3.14 ve 3.9'da geçti, selftest geçti. **5b ✅** `run()`/`run_devin()`/`run_pi()` `RunResult`, `fast()` `FastResult`, `replay()` `ReplayResult` döndürüyor; 18 fonksiyon attribute'u (`run.ok`, `fast.cmds`, `replay.ran` …) ve onları okuyan `getattr(run, …)`'lar kalktı. `main()` her denemenin sonucunu tutuyor; devam denemesi kendi sonucunu getiriyor. `tip()` işin yapılıp yapılmadığını parametre olarak alıyor. `turn.replayed` kancası kalktı: tekrar oynatılan kısayolun adımları `FastResult.ran` ile açıkça log'a gidiyor. `fast()`'in iç adımları ("aç, sonra taşı") aynı sonucu sıfırlayarak paylaşıyor, eskisi gibi. `turn.py`'nin dört fonksiyonu tek bir `RLock` altında (zaman aşımı zamanlayıcısı `end_turn`'ü çağırırken `main()` log yazabiliyordu, S2). Testlerdeki sahte `run`'lar `RunResult` döndürüyor; `test_brain` hiçbir fonksiyonun kendi üzerinde durum tutmadığını denetliyor. 3.14 ve 3.9 tam paket geçti, selftest geçti. **5c ✅** `brain/environ.py` (AskContext) 23 `RABIK_*` değişkeninin tek sahibi: her birinin adı, anlamı ve okunma biçimi orada. Kod `environ.live()`, `environ.ask_dir()`, `environ.in_box()` gibi okuyor; 160 doğrudan okuma/yazma bir codemod ile çevrildi. Değerler bilinçli olarak hâlâ `os.environ`'dan canlı okunuyor: ortam, isteğin AI istemcisine ve onun başlattığı her helper'a ulaştığı kanal, `main()` bazı değerleri istek sırasında yazıyor ve testler `patch.dict(os.environ)` ile değiştiriyor. `replay`'in `RABIK_REQUEST` takası (`environ.requested`) ve `menu_bar_click`'in `RABIK_BAR` koruması (`environ.clicking_menu_bar`) artık `with` blokları. Alt süreç ortamları (`{**os.environ, 'RABIK_ASK': ask}`) süreç sınırı olarak kaldı. `test_brain` başka hiçbir modülün `RABIK_*` okumadığını ve cephedeki isimlerin benzersiz olduğunu denetliyor. 3.14 ve 3.9 tam paket geçti, selftest geçti. **Yapılmayan:** tek bir sinyal/süreç sahibi. 12 `SIGTERM` işleyicisinin her biri farklı bir temizlik yapıyor (toplantı eskisini geri yüklüyor, dikte `stop_workers` çağırmadan çıkıyor); tek sahibe toplamak çıkış davranışını değiştireceği için bırakıldı. |
| 6 — Swift bölme | ✅ | `Rabik.swift` (7.327 satır) `Sources/Rabik/` altında 20 dosyaya bölündü: 42 üst düzey tip (class/struct/enum/protocol) yorumlarıyla birlikte alan dosyalarına (`Overlay/App.swift`, `Hands/Hands.swift`, `Meeting/`, `Drawing/`, `Agents/`, `Settings/`, `Onboarding/`, `Audio/`, `Core/Prefs.swift` …) taşındı. Global sabitler, değişkenler, global fonksiyonlar ve bütün üst düzey kod `main.swift`'te aynı sırada kaldı: `main.swift` dışına taşınan bir global tembel başlatılır, bu da yan etkilerinin zamanını değiştirebilirdi (§7.2'deki 2. tuzak). Her taşınan tipin eski yerinde tek satırlık bir işaret var (`// enum Hands lives in Hands/Hands.swift`); `main.swift` uygulamayı eski sırasıyla okutuyor. `build.sh` `swiftc -module-name Rabik Sources/Rabik/*.swift Sources/Rabik/*/*.swift` derliyor. Testlerde `tests.native_source()` işaretlere tipleri geri koyup tek dosyalık metni yeniden kuruyor (orijinalle dolu satır satır aynı); `tests.native_args()` derleme argümanlarını veriyor; 35 test dosyası buna geçti. **Kanıt:** `swiftc -typecheck` uyarıları bölmeden öncekiyle aynı (20). 3.14 ve 3.9 tam paket geçti, selftest geçti. Bölünmüş kaynaktan arm64 + x86_64 imzalı release build alındı; paketteki helper çalışıyor. |

**SW-SEC1 ✅** (Faz 6'dan sonra): her web view yalnızca kendi yerel sayfasını gösteriyor. `LocalPageOnly` (Core/WebPolicy.swift) bağlantı, form ve geçmiş gezintilerini, ayrıca bir siteye ya da dosyaya giden her yüklemeyi durduruyor; `loadPage` bunu her web view'a veriyor, kendi delegesi olan Settings de ona soruyor. Beş mesaj işleyicisinin hepsi yalnızca sayfanın ana çerçevesini dinliyor (`frameInfo.isMainFrame`). Gerçek bir `WKWebView` ile sınandı: sayfa yükleniyor; script yönlendirmesi, bağlantı tıklaması ve form gönderimi sayfayı değiştirmiyor; iframe mesajı ana çerçeve sayılmıyor (testi VM'de koşuyor). CSP eklenmedi: sayfalar inline script ve olay işleyicilerle çalışıyor, ve model metnini zaten `textContent` ile yazıyorlar; nonce'lu bir CSP sayfaları baştan yazmayı gerektirir.

**SW-S1 ✅ (devamı)**: "çalıştır, sonuna kadar oku, bekle" artık tek bir yardımcıda, `runToEnd(p, out)` (main.swift); 10 çağrı yeri ona geçti, sıra kuralı tek yerde yazılı. Pipe sırası testi değişmeden geçiyor.

Açık kalanlar: ana istekleri sandbox'ta çalıştırma kararı (P1'in kalıcı çözümü).

**brain/ kuralları:** modüller `rabik`'i import etmez; birbirini modül adıyla çağırır (`prefs.pref()`), `from brain.x import isim` ile değil (yalnızca import anında hesaplanan sabitler istisna: `prompts`'taki helper komutları); her modül sahip olduğu isimleri `__all__`'da listeler, cephe bu listeden yönlendirir. Çalışma anında yeniden bağlanan global'ler (`STOPPING`, `_APPS_CACHE`) `__all__`'a girmez; cephe onları `_LIVE` üzerinden sahibinde okur ve yazar. Bir yerel değişken bir modülün adını gölgeliyorsa o fonksiyon modüle paket yoluyla ulaşır (`brain.paths.HOME`). `rabik.py`'nin kendi kodu (selftest) taşınmış bir ismi modül seviyesinde yeniden bağlamaz; sahibine yazar (`brain.skills.SKILLS = …`). `rabik.py`'de fonksiyon ya da sınıf yoktur (yalnızca `_Facade`). `brain/` içinde import döngüsü yoktur. Bu kuralları `tests/test_brain.py` denetler.
