#!/bin/zsh
set -euo pipefail

MAC_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$MAC_DIR/../.." && pwd)"
CORE_DIR="$MAC_DIR/core"
APP="$ROOT/小腊肠.app"
RESOURCES="$APP/Contents/Resources"
RUNTIME="$RESOURCES/runtime"
VENDOR="$RUNTIME/vendor"
APP_ICON="$CORE_DIR/static/icons/AppIcon.icns"
APP_VERSION="${APP_VERSION:-0.6.0}"
PYTHON="${PYTHON:-/usr/bin/python3}"
PYTHON_FRAMEWORK="${PYTHON_FRAMEWORK:-/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework}"
SIGNED_APP="${SIGNED_APP:-/private/tmp/小腊肠.app}"

clear_bundle_xattrs() {
  local target="$1"
  xattr -cr "$target" 2>/dev/null || true
  find "$target" -exec xattr -d com.apple.provenance {} \; 2>/dev/null || true
  find "$target" -exec xattr -d com.apple.FinderInfo {} \; 2>/dev/null || true
  find "$target" -exec xattr -d 'com.apple.fileprovider.fpfs#P' {} \; 2>/dev/null || true
  find "$target" -print0 | xargs -0 xattr -c 2>/dev/null || true
}

sign_macho_files() {
  local target="$1"
  local file filetype
  find "$target" -type f -print0 | while IFS= read -r -d '' file; do
    filetype="$(/usr/bin/file -b "$file" 2>/dev/null || true)"
    if [[ "$filetype" == *Mach-O* ]]; then
      codesign --force --sign - "$file" >/dev/null
    fi
  done
}

sign_runtime_components() {
  local runtime="$1"
  local python_framework="$runtime/python/Python3.framework"
  local python_app="$python_framework/Versions/3.9/Resources/Python.app"
  clear_bundle_xattrs "$runtime"
  sign_macho_files "$runtime"
  if [ -d "$python_app" ]; then
    codesign --force --deep --sign - "$python_app" >/dev/null
    codesign --verify --deep --strict "$python_app"
  fi
  if [ -d "$python_framework" ]; then
    codesign --force --deep --sign - "$python_framework" >/dev/null
  fi
}

rm -rf "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Info.plist"
mkdir -p "$APP/Contents/MacOS" "$RESOURCES" "$RUNTIME" "$VENDOR"

if [ ! -f "$APP_ICON" ]; then
  echo "Missing app icon: $APP_ICON" >&2
  exit 1
fi

for file in "$CORE_DIR"/*.py; do
  cp "$file" "$RUNTIME/$(basename "$file")"
done
cp "$CORE_DIR/config.json" "$RUNTIME/config.json"
cp "$ROOT/requirements.txt" "$RUNTIME/requirements.txt"

for file in \
  control_actions.py \
  control_panel.py \
  service_manager.py
do
  cp "$MAC_DIR/$file" "$RUNTIME/$file"
done

rm -rf "$RUNTIME/static"
cp -R "$CORE_DIR/static" "$RUNTIME/static"
cp "$APP_ICON" "$RESOURCES/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleExecutable</key>
  <string>小腊肠</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>com.fank1ng.xiaolachang</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>小腊肠</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>$APP_VERSION</string>
  <key>CFBundleVersion</key>
  <string>$APP_VERSION</string>
  <key>LSMinimumSystemVersion</key>
  <string>11.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

if [ -d "$PYTHON_FRAMEWORK" ]; then
  rm -rf "$RUNTIME/python"
  mkdir -p "$RUNTIME/python/bin"
  ditto --norsrc "$PYTHON_FRAMEWORK" "$RUNTIME/python/Python3.framework"
  cat > "$RUNTIME/python/bin/python3" <<'PYSH'
#!/bin/zsh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python" "$@"
PYSH
  chmod +x "$RUNTIME/python/bin/python3"
fi

"$PYTHON" - <<'PY' "$VENDOR"
import importlib.util
import shutil
import sys
from pathlib import Path

target = Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)
packages = [
    "aiohttp",
    "aiosignal",
    "async_timeout",
    "attr",
    "attrs",
    "frozenlist",
    "idna",
    "multidict",
    "propcache",
    "typing_extensions",
    "yarl",
]
for package in packages:
    spec = importlib.util.find_spec(package)
    if not spec or not spec.origin:
        continue
    src = Path(spec.origin)
    if src.name == "__init__.py":
        src = src.parent
    dst = target / src.name
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
PY

clang -fobjc-arc -framework Cocoa "$MAC_DIR/ControlApp.m" -o "$APP/Contents/MacOS/小腊肠"
chmod +x "$APP/Contents/MacOS/小腊肠"

find "$APP" -name ".DS_Store" -delete
find "$RUNTIME" \( -name "*.log" -o -name "recent_requests.json" \) -delete
AUTH_LEAK="$(find "$RUNTIME" -path "*/accounts/*/auth.json" -print -quit)"
if [ -n "$AUTH_LEAK" ]; then
  echo "Refusing to build app bundle with account credential: $AUTH_LEAK" >&2
  exit 1
fi

clear_bundle_xattrs "$APP"

echo "Built $APP"

rm -rf "$SIGNED_APP"
ditto --norsrc "$APP" "$SIGNED_APP"
clear_bundle_xattrs "$SIGNED_APP"
sign_runtime_components "$SIGNED_APP/Contents/Resources/runtime"
codesign --force --deep --sign - "$SIGNED_APP" >/dev/null
codesign --verify --deep --strict "$SIGNED_APP"
echo "Signed copy: $SIGNED_APP"
