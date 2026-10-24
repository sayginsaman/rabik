#!/bin/bash
# ./build.sh: builds Rabik.app into ~/Applications, starts it at login, and (re)starts it now. Run it again after any change.
# ./build.sh --release: a universal, Developer ID-signed dist/Rabik-<version>.dmg, notarized when RABIK_NOTARY_PROFILE is set.
#   RABIK_SIGN_ID="Developer ID Application: Name (TEAMID)" RABIK_NOTARY_PROFILE=rabik-notary ./build.sh --release
#   See docs/NOTARIZATION.md.
set -e; cd "$(dirname "$0")"
RELEASE=; [ "$1" = --release ] && RELEASE=1
VERSION=$(tr -d '\n' < VERSION)
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid VERSION: $VERSION"; exit 1; }
IFS=. read -r VERSION_MAJOR VERSION_MINOR VERSION_PATCH <<< "$VERSION"
(( VERSION_MINOR < 1000 && VERSION_PATCH < 1000 )) || { echo "VERSION components must be below 1000"; exit 1; }
BUILD=$((VERSION_MAJOR * 1000000 + VERSION_MINOR * 1000 + VERSION_PATCH))
[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 26 ] || { echo "Rabik needs macOS 26 or later (it uses Apple's new on-device speech)."; exit 1; }
xcode-select -p >/dev/null 2>&1 || { echo "Needs Apple's command line tools. Run: xcode-select --install   then run ./build.sh again."; exit 1; }
if [ -n "$RELEASE" ]; then
  [ -n "$RABIK_SIGN_ID" ] || { echo 'Set RABIK_SIGN_ID to your "Developer ID Application: Name (TEAMID)" identity (security find-identity -v -p codesigning).'; exit 1; }
else
  command -v python3 >/dev/null || { echo "Rabik needs Python 3. Install it, then run ./build.sh again."; exit 1; }
  command -v claude >/dev/null || [ -x ~/.local/bin/claude ] || echo "Note: Claude Code is not installed yet. Rabik's setup window can install it, or you can pick Devin or Pi."
fi
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
# A compiler error must leave the installed app and its resources alone.
# xcrun picks the Xcode or Command Line Tools compiler with its macOS SDK, never another swiftc first on PATH.
if [ -n "$RELEASE" ]; then
  for ARCH in arm64 x86_64; do xcrun swiftc -O -module-name Rabik -target "$ARCH-apple-macos26.0" Rabik.swift -o "$STAGE/Rabik-$ARCH"; done
  lipo -create "$STAGE/Rabik-arm64" "$STAGE/Rabik-x86_64" -output "$STAGE/Rabik"
  APP=dist/Rabik.app; rm -rf "$APP"
else
  xcrun swiftc -O -module-name Rabik -target "$(uname -m)-apple-macos26.0" Rabik.swift -o "$STAGE/Rabik"
  APP=~/Applications/Rabik.app   # in Applications so System Settings can list it for permissions
fi
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/ui"
cp rabik.py "$APP/Contents/Resources/"
cp ui/*.html ui/*.js ui/*.png "$APP/Contents/Resources/ui/"
cp ui/AppIcon.icns "$APP/Contents/Resources/"
# The in-app Git updater pulls and rebuilds this source folder; a release has none, so its updater stays off.
SOURCE=$([ -n "$RELEASE" ] || printf '<key>RabikSource</key><string>%s</string>' "$(pwd)")
cat > "$APP/Contents/Info.plist" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.rabik.app</string>
<key>CFBundleName</key><string>Rabik</string>
<key>CFBundleExecutable</key><string>Rabik</string>
<key>CFBundleVersion</key><string>$BUILD</string>
<key>CFBundleShortVersionString</key><string>$VERSION</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>LSMinimumSystemVersion</key><string>26.0</string>
$SOURCE
<key>LSUIElement</key><true/>
<key>NSMicrophoneUsageDescription</key><string>Rabik listens when you use its shortcut or microphone button.</string>
<key>NSAppleEventsUsageDescription</key><string>Rabik controls apps like Finder, Chrome and Music when you ask it to.</string>
<key>NSCalendarsFullAccessUsageDescription</key><string>Rabik reads your calendar, adds events you request, and asks before moving or deleting existing events. Calendar details are sent to your chosen AI model.</string>
<key>NSSpeechRecognitionUsageDescription</key><string>Rabik turns your words into text on this Mac.</string>
</dict></plist>
P
mv "$STAGE/Rabik" "$APP/Contents/MacOS/Rabik"
if [ -n "$RELEASE" ]; then
  # Hardened Runtime and a secure timestamp are what notarization requires; the entitlements keep mic, calendar and Apple Events.
  codesign --force --options runtime --timestamp --entitlements Rabik.entitlements --sign "$RABIK_SIGN_ID" "$APP"
  codesign --verify --strict --verbose=2 "$APP"
  notarize() {   # waits for Apple's verdict; anything but Accepted stops the release
    local out status
    out=$(xcrun notarytool submit "$1" --keychain-profile "$RABIK_NOTARY_PROFILE" --wait --output-format json) || { echo "$out"; exit 1; }
    status=$(/usr/bin/plutil -extract status raw -o - - <<< "$out")
    [ "$status" = Accepted ] || { echo "Notarization of $1: $status. Details: xcrun notarytool log $(/usr/bin/plutil -extract id raw -o - - <<< "$out") --keychain-profile $RABIK_NOTARY_PROFILE"; exit 1; }
  }
  if [ -n "$RABIK_NOTARY_PROFILE" ]; then   # staple the app too, so a copy taken out of the disk image opens offline
    ditto -c -k --keepParent "$APP" "$STAGE/Rabik.zip"
    notarize "$STAGE/Rabik.zip"
    xcrun stapler staple "$APP"
  fi
  DMG="dist/Rabik-$VERSION.dmg"
  mkdir "$STAGE/dmg"; ditto "$APP" "$STAGE/dmg/Rabik.app"; ln -s /Applications "$STAGE/dmg/Applications"
  rm -f "$DMG"; hdiutil create -quiet -volname Rabik -srcfolder "$STAGE/dmg" -fs HFS+ -format UDZO "$DMG"
  codesign --force --timestamp --sign "$RABIK_SIGN_ID" "$DMG"
  if [ -n "$RABIK_NOTARY_PROFILE" ]; then
    notarize "$DMG"
    xcrun stapler staple "$DMG"
    spctl --assess --type open --context context:primary-signature --verbose "$DMG"
    echo "Built and notarized $DMG"
  else
    echo "Built $DMG, signed but not notarized: set RABIK_NOTARY_PROFILE to notarize it."
  fi
  exit 0
fi
# With a code-signing identity named "Rabik Local Signing" in the keychain, macOS keeps permissions across
# rebuilds and auto-updates; ad hoc signing would ask for every permission again after each one. So make it once.
ID=$(security find-identity -p codesigning | awk '/Rabik Local Signing/{print $2; exit}')
if [ -z "$ID" ]; then
  K=$(mktemp -d)
  /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 7300 -subj "/CN=Rabik Local Signing" -addext "extendedKeyUsage=critical,codeSigning" \
    -addext "keyUsage=critical,digitalSignature" -keyout "$K/k.pem" -out "$K/c.pem" 2>/dev/null &&
  /usr/bin/openssl pkcs12 -export -inkey "$K/k.pem" -in "$K/c.pem" -out "$K/a.p12" -passout pass:rabik 2>/dev/null &&
  security import "$K/a.p12" -P rabik -T /usr/bin/codesign >/dev/null 2>&1 || true   # fails quietly: ad hoc still works
  rm -rf "$K"
  ID=$(security find-identity -p codesigning | awk '/Rabik Local Signing/{print $2; exit}')
fi
codesign -s "${ID:--}" --force "$APP"
# register with macOS, or System Settings can't list it for permissions
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"
AGENT=~/Library/LaunchAgents/com.rabik.app.plist   # starts at login, restarts if it crashes (Quit stays quit)
mkdir -p ~/Library/LaunchAgents ~/.config/rabik
cat > "$AGENT" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.rabik.app</string>
<key>ProgramArguments</key><array><string>$APP/Contents/MacOS/Rabik</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
<key>StandardErrorPath</key><string>$HOME/.config/rabik/app.err</string>
</dict></plist>
P
[ -n "$RABIK_NO_RESTART" ] && exit 0   # the app's own updater restarts it when idle
# Reload the job so launchd refreshes its executable signing requirement after a rebuild.
launchctl bootout gui/$(id -u)/com.rabik.app 2>/dev/null || true
pkill -f "$APP/Contents/MacOS/Rabik$" 2>/dev/null && sleep 1   # stop a copy opened by hand too
# bootout can return before the job has finished unloading.
launchctl bootstrap gui/$(id -u) "$AGENT" 2>/dev/null || { sleep 1; launchctl bootstrap gui/$(id -u) "$AGENT" 2>/dev/null || {
  echo "Could not add Rabik to Login Items; opening it directly instead."
  open "$APP"
}; }
echo "Rabik is running. Hold Control+Option+Space and talk."
