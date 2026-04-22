#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$ROOT_DIR/dist/NiimbotPopup.app"
PRODUCT_NAME="NiimbotPopup"

cd "$ROOT_DIR/mac-app"
swift build

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

cp ".build/debug/$PRODUCT_NAME" "$APP_DIR/Contents/MacOS/$PRODUCT_NAME"

# Generate app icon
ICONSET="$ROOT_DIR/mac-app/AppIcon.iconset"
python3 "$ROOT_DIR/mac-app/generate_icon.py" "$ICONSET"
iconutil -c icns "$ICONSET" -o "$APP_DIR/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET"

cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>$PRODUCT_NAME</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>com.adam.niimbot.popup</string>
  <key>CFBundleName</key>
  <string>Niimbot</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

printf "%s\n" "$ROOT_DIR" > "$APP_DIR/Contents/Resources/repo-root.txt"

# Resolve the Python interpreter that actually has the niimbot deps and bake its
# absolute path into the bundle. Launchd/Finder don't inherit the user's PATH, so
# /usr/bin/env python3 resolves to Xcode's Python which lacks our deps.
PYTHON_PATH="$(command -v python3 || true)"
if [[ -z "$PYTHON_PATH" ]]; then
  echo "ERROR: no python3 on PATH" >&2
  exit 1
fi
# Resolve pyenv shims to real executables so the app works without pyenv init.
RESOLVED_PYTHON="$("$PYTHON_PATH" -c 'import sys; print(sys.executable)')"
if ! "$RESOLVED_PYTHON" -c 'import bleak, claude_agent_sdk' 2>/dev/null; then
  echo "WARNING: $RESOLVED_PYTHON is missing niimbot deps (bleak / claude_agent_sdk)." >&2
  echo "         Run: pip install -e '.[app]' in that interpreter." >&2
fi
printf "%s\n" "$RESOLVED_PYTHON" > "$APP_DIR/Contents/Resources/python-path.txt"
echo "Bundled Python: $RESOLVED_PYTHON"

chmod +x "$APP_DIR/Contents/MacOS/$PRODUCT_NAME"

echo "Built $APP_DIR"
