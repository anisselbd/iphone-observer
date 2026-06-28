#!/usr/bin/env bash
# Construit un bundle iPhoneObserver.app double-cliquable.
# Le collector Python reste un sidecar separe (lance au runtime), jamais embarque
# dans le binaire: frontiere de licence GPL preservee.
set -euo pipefail
cd "$(dirname "$0")"

echo "Compilation release..."
swift build -c release

APP="iPhoneObserver.app"
BIN=".build/release/iPhoneObserver"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN" "$APP/Contents/MacOS/iPhoneObserver"
chmod +x "$APP/Contents/MacOS/iPhoneObserver"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>            <string>iPhoneObserver</string>
    <key>CFBundleDisplayName</key>     <string>iPhone Observer</string>
    <key>CFBundleIdentifier</key>      <string>local.iphone-observer</string>
    <key>CFBundleExecutable</key>      <string>iPhoneObserver</string>
    <key>CFBundlePackageType</key>     <string>APPL</string>
    <key>CFBundleShortVersionString</key> <string>0.1.0</string>
    <key>CFBundleVersion</key>         <string>1</string>
    <key>LSMinimumSystemVersion</key>  <string>14.0</string>
    <key>NSHighResolutionCapable</key> <true/>
    <key>LSUIElement</key>             <false/>
</dict>
</plist>
PLIST

echo "Cree: $PWD/$APP"
echo "Lance-le avec: open \"$PWD/$APP\""
echo "(1re fois, si Gatekeeper rale: clic droit > Ouvrir)"
