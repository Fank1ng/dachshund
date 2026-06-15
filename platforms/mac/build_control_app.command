#!/bin/zsh
set -euo pipefail

MAC_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$MAC_DIR/../.." && pwd)"
CORE_DIR="$MAC_DIR/core"
APP_LINK="$ROOT/XiaoLaChang.app"
LEGACY_APP_LINK="$ROOT/小腊肠.app"
APP="${APP:-$HOME/Applications/XiaoLaChang.app}"
LEGACY_APP="${LEGACY_APP:-$HOME/Applications/小腊肠.app}"
RESOURCES="$APP/Contents/Resources"
RUNTIME="$RESOURCES/runtime"
VENDOR="$RUNTIME/vendor"
APP_ICON="$CORE_DIR/static/icons/AppIcon.icns"
VERSION_FILE="$ROOT/VERSION"
APP_VERSION="${APP_VERSION:-$(tr -d '[:space:]' < "$VERSION_FILE")}"
PYTHON="${PYTHON:-/usr/bin/python3}"
PYTHON_FRAMEWORK="${PYTHON_FRAMEWORK:-/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework}"
SIGNED_APP="${SIGNED_APP:-/private/tmp/XiaoLaChang.app}"

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
      xattr -c "$file" 2>/dev/null || true
      codesign --force --sign - "$file" >/dev/null
      xattr -c "$file" 2>/dev/null || true
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
    clear_bundle_xattrs "$python_app"
    codesign --verify --deep --strict "$python_app"
  fi
  if [ -d "$python_framework" ]; then
    codesign --force --deep --sign - "$python_framework" >/dev/null
  fi
}

if [ "$LEGACY_APP" != "$APP" ]; then
  rm -rf "$LEGACY_APP"
fi
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RESOURCES" "$RUNTIME" "$VENDOR"

if [ ! -f "$APP_ICON" ]; then
  echo "Missing app icon: $APP_ICON" >&2
  exit 1
fi

if [ -z "$APP_VERSION" ]; then
  echo "VERSION is empty." >&2
  exit 1
fi

"$PYTHON" - <<'PY' "$ROOT"
import filecmp
import sys
from pathlib import Path

root = Path(sys.argv[1])
pairs = [
    ("src/core/proxy.py", "platforms/mac/core/proxy.py"),
    ("src/core/proxy_core.py", "platforms/mac/core/proxy_core.py"),
    ("src/core/usage_stats.py", "platforms/mac/core/usage_stats.py"),
    ("src/core/version.py", "platforms/mac/core/version.py"),
    ("src/core/runtime_manifest.py", "platforms/mac/core/runtime_manifest.py"),
    ("src/core/static/index.html", "platforms/mac/core/static/index.html"),
]
failed = []
for left, right in pairs:
    if not (root / left).is_file() or not (root / right).is_file() or not filecmp.cmp(root / left, root / right, shallow=False):
        failed.append(f"{left} != {right}")
if failed:
    print("Refusing to build with unsynced mac runtime sources:", file=sys.stderr)
    for item in failed:
        print(f"  {item}", file=sys.stderr)
    sys.exit(1)
PY

for file in "$CORE_DIR"/*.py; do
  cp "$file" "$RUNTIME/$(basename "$file")"
done
cp "$VERSION_FILE" "$RUNTIME/VERSION"
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
if [ ! -f "$RUNTIME/static/icons/dog-head.png" ] && [ ! -f "$RESOURCES/AppIcon.icns" ]; then
  echo "Refusing to build without a menu bar icon resource." >&2
  exit 1
fi

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleExecutable</key>
  <string>XiaoLaChang</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>com.fank1ng.xiaolachang</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>小腊肠</string>
  <key>CFBundleDisplayName</key>
  <string>小腊肠</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>$APP_VERSION</string>
  <key>CFBundleVersion</key>
  <string>$APP_VERSION</string>
  <key>LSMinimumSystemVersion</key>
  <string>11.0</string>
  <key>LSUIElement</key>
  <true/>
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

clang -fobjc-arc -framework Cocoa "$MAC_DIR/ControlApp.m" -o "$APP/Contents/MacOS/XiaoLaChang"
chmod +x "$APP/Contents/MacOS/XiaoLaChang"

find "$APP" -name ".DS_Store" -delete
find "$RUNTIME" \( -name "*.log" -o -name "recent_requests.json" \) -delete
if rg -n "精确捕获|无 usage" "$RUNTIME" "$MAC_DIR/ControlApp.m" >/dev/null; then
  echo "Refusing to build with removed token usage copy still present." >&2
  exit 1
fi
if ! rg -n "/api/token-usage/events" "$RUNTIME/proxy.py" "$RUNTIME/static/index.html" >/dev/null; then
  echo "Refusing to build without token usage events API wiring." >&2
  exit 1
fi
AUTH_LEAK="$(find "$RUNTIME" -path "*/accounts/*/auth.json" -print -quit)"
if [ -n "$AUTH_LEAK" ]; then
  echo "Refusing to build app bundle with account credential: $AUTH_LEAK" >&2
  exit 1
fi

"$PYTHON" - <<'PY' "$RUNTIME" "$APP_VERSION"
import json
import sys
from pathlib import Path

runtime = Path(sys.argv[1])
expected_version = sys.argv[2]
sys.path.insert(0, str(runtime))
from runtime_manifest import BUILD_MANIFEST, compare_manifests, generate_manifest, write_manifest
from version import app_version

observed_version = app_version(runtime)
if observed_version != expected_version:
    raise SystemExit(f"runtime VERSION mismatch: expected {expected_version}, observed {observed_version}")
build = write_manifest(runtime, manifest_name=BUILD_MANIFEST)
runtime_manifest = generate_manifest(runtime, manifest_name="runtime_manifest.json")
check = compare_manifests(build, runtime_manifest)
if not check.get("ok"):
    raise SystemExit("bundle runtime manifest self-check failed: " + json.dumps(check, sort_keys=True))
PY

clear_bundle_xattrs "$APP"
sign_runtime_components "$APP/Contents/Resources/runtime"
clear_bundle_xattrs "$APP"
codesign --force --deep --sign - "$APP" >/dev/null
codesign --verify --deep --strict "$APP"

echo "Built $APP"

rm -rf "$SIGNED_APP"
ditto --norsrc "$APP" "$SIGNED_APP"
clear_bundle_xattrs "$SIGNED_APP"
codesign --force --deep --sign - "$SIGNED_APP" >/dev/null
codesign --verify --deep --strict "$SIGNED_APP"
echo "Signed copy: $SIGNED_APP"
if [ "$APP" != "$APP_LINK" ]; then
  rm -rf "$APP_LINK"
  ln -s "$APP" "$APP_LINK"
  echo "Workspace link: $APP_LINK -> $APP"
fi
if [ -L "$LEGACY_APP_LINK" ]; then
  rm -f "$LEGACY_APP_LINK"
fi
SYSTEM_APP_LINK="/Applications/XiaoLaChang.app"
LEGACY_SYSTEM_APP_LINK="/Applications/小腊肠.app"
if [ -d /Applications ] && [ -w /Applications ] && [ "$APP" != "$SYSTEM_APP_LINK" ]; then
  rm -rf "$SYSTEM_APP_LINK"
  ln -s "$APP" "$SYSTEM_APP_LINK"
  echo "Applications link: $SYSTEM_APP_LINK -> $APP"
fi
if [ -L "$LEGACY_SYSTEM_APP_LINK" ]; then
  rm -f "$LEGACY_SYSTEM_APP_LINK"
fi
