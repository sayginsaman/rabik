# Rabik — İmzalama ve Notarization

Hedef: Rabik'i hazır, Developer ID ile imzalanmış ve Apple tarafından notarize edilmiş bir `.dmg` olarak dağıtmak. Kullanıcı tarayıcıdan indirip açtığında Gatekeeper uyarısı çıkmamalı.

> Not: Eski Atticus modelinde uygulama kullanıcının Mac'inde `swiftc` ile derleniyordu (`curl | bash`). Yerelde derlenen uygulama karantinaya alınmadığı için notarization gerekmiyordu. Hazır `.dmg` modeline geçince aşağıdaki adımlar zorunlu.

## 1. Apple Developer hesabında yapacakların

1. **Apple Developer Program üyeliği** (yıllık ücretli). Organizasyon adına yayınlayacaksan D-U-N-S numarası gerekir.
2. **Team ID'ni not et.** developer.apple.com → Account → Membership details.
3. **"Developer ID Application" sertifikası oluştur:**
   - Mac'te: Keychain Access → Certificate Assistant → *Request a Certificate From a Certificate Authority…* → "Saved to disk" ile bir CSR oluştur.
   - developer.apple.com → Certificates, Identifiers & Profiles → Certificates → **+** → *Developer ID Application* → CSR'ı yükle → sertifikayı indir → çift tıkla. Sertifika, private key ile birlikte login keychain'e girer.
   - Organizasyon hesabında Developer ID sertifikasını yalnızca *Account Holder* oluşturabilir.
   - Kontrol: `security find-identity -v -p codesigning` çıktısında `Developer ID Application: Adın Soyadın (TEAMID)` görünmeli. Bu tam metin aşağıdaki `RABIK_SIGN_ID` değeri olacak.
   - `.p12` olarak yedekle; private key kaybolursa sertifika kullanılamaz.
4. **Notarization kimlik bilgisi.** İkisinden birini seç:
   - **App-specific password** (en kolayı): appleid.apple.com → Sign-In and Security → App-Specific Passwords → oluştur.
   - **App Store Connect API key** (CI için daha iyi): App Store Connect → Users and Access → Integrations → Team Keys → anahtar oluştur (rol: Developer). `.p8` dosyası, Key ID ve Issuer ID gerekir.
5. **Kimlik bilgisini keychain'e kaydet** (bir kere):

   ```bash
   xcrun notarytool store-credentials "rabik-notary" --apple-id "you@example.com" --team-id "TEAMID" --password "xxxx-xxxx-xxxx-xxxx"
   ```

   API key ile: `xcrun notarytool store-credentials "rabik-notary" --key AuthKey_XXXX.p8 --key-id XXXX --issuer <issuer-uuid>`
6. **Bundle ID:** `com.rabik.app`. Özel bir capability (iCloud, push vb.) kullanılmadığı için Developer ID dağıtımında App ID kaydı **zorunlu değil**.

## 2. Kodda hazırlananlar

| Dosya | Ne yapıyor |
|---|---|
| `Rabik.entitlements` | Hardened Runtime izinleri: mikrofon (`device.audio-input`), takvim (`personal-information.calendars`), Apple Events (`automation.apple-events`). Bunlar olmadan imzalı uygulama, kullanıcı izin verse bile bu erişimleri sessizce kaybeder. |
| `build.sh --release` | Universal (arm64 + x86_64) binary üretir, `.app`'i `dist/` altında hazırlar. Ardından Hardened Runtime + secure timestamp ile imzalar, notarize edip staple'lar, `.dmg` oluşturur ve onu da imzalayıp notarize edip staple'lar. |

Kullanım:

```bash
RABIK_SIGN_ID="Developer ID Application: Adın Soyadın (TEAMID)" RABIK_NOTARY_PROFILE=rabik-notary ./build.sh --release
```

Çıktı: `dist/Rabik-<VERSION>.dmg`. Notarization genelde birkaç dakika sürer. Reddedilirse script durur ve Apple'ın log'unu getirecek `xcrun notarytool log …` komutunu yazdırır.

`RABIK_NOTARY_PROFILE` verilmezse script yalnızca imzalı (notarize edilmemiş) bir `.dmg` üretir. Apple'a göndermeden önce imzayı ve entitlements'ı denemek için kullanışlı.

## 3. Doğrulama

```bash
codesign --verify --deep --strict --verbose=2 dist/Rabik.app
codesign -d --entitlements - dist/Rabik.app            # üç entitlement görünmeli
spctl -a -t exec -vvv dist/Rabik.app                    # source=Notarized Developer ID
xcrun stapler validate dist/Rabik-<VERSION>.dmg
```

Son test: `.dmg`'yi tarayıcıyla indir (karantina bayrağı alsın), temiz bir kullanıcı hesabında aç, `/Applications`'a taşı, çalıştır.

## 4. Hazır `.dmg` dağıtımından önce kodda yapılması gerekenler

Bunlar notarization'ı engellemez ama dağıtılan uygulamanın düzgün çalışması için gerekli:

1. **Girişte başlatma.** Şu an `build.sh` bir LaunchAgent (`~/Library/LaunchAgents/com.rabik.app.plist`) kuruyor; Settings'teki "login" anahtarı da onu `launchctl` ile açıp kapatıyor. `.dmg`'den kurulan uygulamada bu dosya yok. Bu yüzden `SMAppService.mainApp.register()` / `unregister()` gerekiyor (ServiceManagement, macOS 13+).
2. **Güncellemeler.** git-pull + yeniden derleme güncelleyicisi release build'de kendiliğinden kapalı: Info.plist'te `RabikSource` anahtarı olmadığı için Settings "Preview build" gösterir. İmzalı güncelleme için Sparkle 2 (EdDSA imzalı appcast) veya en azından GitHub Releases'tan "yeni sürüm var" kontrolü eklenmeli.
3. **Python bağımlılığı.** Uygulama `rabik.py`'yi sistemdeki `python3` ile çalıştırıyor. Command Line Tools kurulu değilse `/usr/bin/python3` kurulum penceresi açar. Seçenekler:
   - CLT'yi ön koşul olarak belgelemek (kısa vade).
   - İmzalı bir Python runtime'ı uygulamaya gömmek. İçindeki tüm `.dylib`/`.so` dosyaları Developer ID ve Hardened Runtime ile imzalanmalı.
   - Uzun vadede beyni Swift'e taşımak.

   Ayrıca Homebrew Python'u varsa o tercih ediliyor; bu, kullanıcıdan kullanıcıya farklı sürüm demek.
4. **Paketin içine yazmamak.** İmza `Contents/Resources` altındaki `rabik.py` ve `ui/` dosyalarını da mühürlüyor. Python'un `.pyc` dosyalarını paket içine yazması imzayı bozar. Şu an `sys.pycache_prefix` ile `~/Library/Caches/Rabik`'e yönlendiriliyor; modüler refactor'da bu korunmalı.
5. **Claude Code CLI** hâlâ çalışma zamanı bağımlılığı (kullanıcı kendisi kuruyor). Bu, notarization'ı etkilemez.
6. **Telemetri ve linkler.** PostHog anahtarı boş, yani telemetri kapalı. Repo adresi `https://github.com/sayginsaman/rabik` (2026-10-25'te kondu; depo henüz oluşturulmadı). Kendi değerlerini koyduğunda: `brain/paths.py` → `REPOSITORY`, `brain/telemetry.py` → `POSTHOG_KEY`, `Sources/Rabik/main.swift` → `repository`.
