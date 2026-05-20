#!/bin/zsh
set -euo pipefail

MAC_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$MAC_DIR/../.." && pwd)"
APP_NAME="Codex Proxy Control.app"
APP="$ROOT/$APP_NAME"
BUILD_DIR="$ROOT/build"
STAGE_LINK="$BUILD_DIR/dmg-stage"
STAGE="${TMPDIR:-/private/tmp}/codexproxyapi-dmg-stage"
DIST="$ROOT/dist"

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

"$MAC_DIR/build_control_app.command"

VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"
DMG_NAME="Codex-Proxy-Control-${VERSION}-mac.dmg"
DMG_TMP="$BUILD_DIR/${DMG_NAME%.dmg}.tmp.dmg"
DMG="$DIST/$DMG_NAME"

rm -rf "$STAGE" "$STAGE_LINK"
mkdir -p "$STAGE" "$DIST" "$BUILD_DIR"
ln -s "$STAGE" "$STAGE_LINK"

if [ ! -d "$APP" ]; then
  echo "Missing app bundle: $APP" >&2
  exit 1
fi

if [ -d "$APP/Contents/Resources/runtime/accounts" ]; then
  echo "Refusing to package accounts inside app runtime." >&2
  exit 1
fi

AUTH_LEAK="$(find "$APP" -name "auth.json" -print -quit)"
if [ -n "$AUTH_LEAK" ]; then
  echo "Refusing to package credential file: $AUTH_LEAK" >&2
  exit 1
fi

ditto --norsrc "$APP" "$STAGE/$APP_NAME"
ln -s /Applications "$STAGE/Applications"

cat > "$STAGE/首次打开说明.txt" <<'TXT'
Codex Proxy Control 首次打开说明

1. 把 Codex Proxy Control.app 拖到 Applications。
2. 如果 macOS 提示“无法验证开发者”，请右键点击 App，选择“打开”，再在弹窗中确认。
3. 如果仍被拦截，进入“系统设置” -> “隐私与安全性”，允许打开 Codex Proxy Control。
4. 打开 App 后点击“启动/修复”，然后按界面提示添加账号并启用代理。

本版本采用本地/ad-hoc 签名，没有 Apple 公证，因此首次打开可能需要手动放行。
TXT

find "$STAGE" -name ".DS_Store" -delete
find "$STAGE" \( -name "*.log" -o -name "recent_requests.json" \) -delete
clear_bundle_xattrs "$STAGE/$APP_NAME"
sign_runtime_components "$STAGE/$APP_NAME/Contents/Resources/runtime"

codesign --force --deep --sign - "$STAGE/$APP_NAME" >/dev/null
codesign --verify --deep --strict "$STAGE/$APP_NAME"
PYTHON_APP="$STAGE/$APP_NAME/Contents/Resources/runtime/python/Python3.framework/Versions/3.9/Resources/Python.app"
if [ -d "$PYTHON_APP" ]; then
  codesign --verify --deep --strict "$PYTHON_APP"
fi

rm -f "$DMG_TMP" "$DMG"
hdiutil create \
  -volname "Codex Proxy Control $VERSION" \
  -srcfolder "$STAGE" \
  -fs HFS+ \
  -format UDZO \
  -ov \
  "$DMG_TMP"
hdiutil verify "$DMG_TMP"
mv "$DMG_TMP" "$DMG"
xattr -cr "$DMG"

echo "Built DMG: $DMG"
