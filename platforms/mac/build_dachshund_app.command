#!/bin/zsh
set -euo pipefail

MAC_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$MAC_DIR/../.." && pwd)"
CORE_DIR="$ROOT/src/core"
ELECTRON_APP="$ROOT/node_modules/electron/dist/Electron.app"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
DIST="$ROOT/dist"
BUILD_ROOT="${TMPDIR:-/private/tmp}/dachshund-build"
APP="$BUILD_ROOT/dachshund.app"
DMG_ROOT="$BUILD_ROOT/dmg"
DIST_APP="$DIST/dachshund.app"
RUNTIME="$APP/Contents/Resources/runtime"
APP_SRC="$APP/Contents/Resources/app"
VENDOR="$RUNTIME/vendor"
PYTHON="${PYTHON:-/usr/bin/python3}"

clean_bundle_xattrs() {
  local bundle="$1"
  local paths=(
    "$bundle"
    "$bundle/Contents/Frameworks/Electron Helper.app"
    "$bundle/Contents/Frameworks/Electron Helper (GPU).app"
    "$bundle/Contents/Frameworks/Electron Helper (Plugin).app"
    "$bundle/Contents/Frameworks/Electron Helper (Renderer).app"
    "$bundle/Contents/Frameworks/Electron Framework.framework"
    "$bundle/Contents/Frameworks/Mantle.framework"
    "$bundle/Contents/Frameworks/ReactiveObjC.framework"
    "$bundle/Contents/Frameworks/Squirrel.framework"
  )
  for item in "${paths[@]}"; do
    xattr -d com.apple.FinderInfo "$item" 2>/dev/null || true
    xattr -d 'com.apple.fileprovider.fpfs#P' "$item" 2>/dev/null || true
  done
}

if [ ! -d "$ELECTRON_APP" ]; then
  echo "Missing Electron runtime. Run: npm install" >&2
  exit 1
fi

rm -rf "$BUILD_ROOT" "$DIST_APP"
mkdir -p "$DIST" "$BUILD_ROOT" "$DMG_ROOT"
ditto --norsrc --noextattr --noqtn --noacl "$ELECTRON_APP" "$APP"
mv "$APP/Contents/MacOS/Electron" "$APP/Contents/MacOS/dachshund"
mkdir -p "$RUNTIME" "$VENDOR" "$APP_SRC/platforms"

cp "$ROOT/package.json" "$APP_SRC/package.json"
mkdir -p "$APP_SRC/app"
cp -R "$ROOT/app/electron" "$APP_SRC/app/electron"

for file in "$CORE_DIR"/*.py; do
  cp "$file" "$RUNTIME/$(basename "$file")"
done
cp "$ROOT/VERSION" "$RUNTIME/VERSION"
cp "$CORE_DIR/config.json" "$RUNTIME/config.json"
cp "$ROOT/requirements.txt" "$RUNTIME/requirements.txt"
for file in control_actions.py service_manager.py; do
  cp "$MAC_DIR/$file" "$RUNTIME/$file"
done
cp -R "$CORE_DIR/static" "$RUNTIME/static"
cp "$CORE_DIR/static/icons/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

"$PYTHON" - <<'PY' "$VENDOR"
import importlib.util
import shutil
import sys
from pathlib import Path

target = Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)
for package in [
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
]:
    spec = importlib.util.find_spec(package)
    if not spec or not spec.origin:
        continue
    src = Path(spec.origin)
    if src.name == "__init__.py":
        src = src.parent
    dst = target / src.name
    if dst.exists():
        shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
    shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
PY

PYTHONPATH="$RUNTIME" "$PYTHON" - <<'PY' "$RUNTIME"
import sys
from pathlib import Path
from runtime_manifest import write_manifest

write_manifest(Path(sys.argv[1]), manifest_name="build_manifest.json")
PY

/usr/libexec/PlistBuddy -c "Set :CFBundleExecutable dachshund" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.fank1ng.dachshund" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName Dachshund" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName Dachshund" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile AppIcon" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$APP/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "$APP/Contents/Info.plist"

find "$APP" -name ".DS_Store" -delete
dot_clean -m "$APP" 2>/dev/null || true
xattr -cr "$APP" 2>/dev/null || true
xattr -rd com.apple.FinderInfo "$APP" 2>/dev/null || true
xattr -rd 'com.apple.fileprovider.fpfs#P' "$APP" 2>/dev/null || true
find "$APP" -exec xattr -c {} \; 2>/dev/null || true
find "$APP" -exec xattr -d com.apple.provenance {} \; 2>/dev/null || true
find "$APP" -exec xattr -d com.apple.FinderInfo {} \; 2>/dev/null || true
find "$APP" -exec xattr -d 'com.apple.fileprovider.fpfs#P' {} \; 2>/dev/null || true
clean_bundle_xattrs "$APP"
codesign --force --deep --sign - "$APP" >/dev/null

DMG="$DIST/dachshund-${VERSION}-mac.dmg"
ditto --norsrc --noextattr --noqtn --noacl "$APP" "$DIST_APP"
xattr -dr com.apple.FinderInfo "$DIST_APP" 2>/dev/null || true
xattr -dr 'com.apple.fileprovider.fpfs#P' "$DIST_APP" 2>/dev/null || true
find "$DIST_APP" \( -name "*.app" -o -name "*.framework" \) -exec xattr -c {} \; 2>/dev/null || true
xattr -c "$DIST_APP" 2>/dev/null || true
clean_bundle_xattrs "$DIST_APP"
rm -f "$DMG"
ditto --norsrc --noextattr --noqtn --noacl "$DIST_APP" "$DMG_ROOT/dachshund.app"
ln -s /Applications "$DMG_ROOT/Applications"
hdiutil create -volname "Dachshund" -srcfolder "$DMG_ROOT" -ov -format UDZO "$DMG" >/dev/null
clean_bundle_xattrs "$DIST_APP"

echo "$DIST_APP"
echo "$DMG"
