#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Codex Proxy Control.app"
APP="$ROOT/$APP_NAME"
BUILD_DIR="$ROOT/build"
STAGE="$BUILD_DIR/dmg-stage"
DIST="$ROOT/dist"

"$ROOT/build_control_app.command"

VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"
DMG_NAME="Codex-Proxy-Control-${VERSION}-mac.dmg"
DMG_TMP="$BUILD_DIR/${DMG_NAME%.dmg}.tmp.dmg"
DMG="$DIST/$DMG_NAME"

rm -rf "$STAGE"
mkdir -p "$STAGE" "$DIST"

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
xattr -cr "$STAGE/$APP_NAME"

codesign --force --deep --sign - "$STAGE/$APP_NAME" >/dev/null
codesign --verify --deep --strict "$STAGE/$APP_NAME"

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
