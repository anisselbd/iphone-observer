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

# Icone: generee si absente (necessite python3 + Pillow).
if [ ! -f "Resources/AppIcon.icns" ]; then
    echo "Generation de l'icone..."
    python3 make-icon.py || echo "(icone ignoree: Pillow absent)"
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/iPhoneObserver"
chmod +x "$APP/Contents/MacOS/iPhoneObserver"
[ -f "Resources/AppIcon.icns" ] && cp "Resources/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>            <string>iPhoneObserver</string>
    <key>CFBundleDisplayName</key>     <string>iPhone Observer</string>
    <key>CFBundleIdentifier</key>      <string>local.iphone-observer</string>
    <key>CFBundleExecutable</key>      <string>iPhoneObserver</string>
    <key>CFBundleIconFile</key>        <string>AppIcon</string>
    <key>CFBundlePackageType</key>     <string>APPL</string>
    <key>CFBundleShortVersionString</key> <string>0.1.0</string>
    <key>CFBundleVersion</key>         <string>1</string>
    <key>LSMinimumSystemVersion</key>  <string>14.0</string>
    <key>NSHighResolutionCapable</key> <true/>
    <key>LSUIElement</key>             <false/>
</dict>
</plist>
PLIST

# Signature ad-hoc: donne une identite stable au bundle, requise pour que les
# notifications macOS (UNUserNotificationCenter) soient autorisees sur une app
# locale non distribuee.
echo "Signature ad-hoc..."
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || echo "(codesign ignore)"

# Force LaunchServices a relire le bundle, sinon l'icone reste en cache obsolete
# quand on reconstruit au meme chemin.
LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[ -x "$LSREG" ] && "$LSREG" -f "$PWD/$APP" >/dev/null 2>&1 || true

echo "Cree: $PWD/$APP"
echo "Lance-le avec: open \"$PWD/$APP\""
echo "(1re fois, si Gatekeeper rale: clic droit > Ouvrir)"
