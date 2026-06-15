#!/bin/zsh
set -euo pipefail

MAC_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$MAC_DIR/../.." && pwd)"
APP_NAME="XiaoLaChang.app"
BUILD_DIR="$ROOT/build"
APP_BUILD_DIR="${APP_BUILD_DIR:-${TMPDIR:-/private/tmp}/xiaolachang-build}"
APP="${APP:-$APP_BUILD_DIR/$APP_NAME}"
SIGNED_APP="${SIGNED_APP:-$APP_BUILD_DIR/Signed-$APP_NAME}"
STAGE_LINK="$BUILD_DIR/dmg-stage"
STAGE="${TMPDIR:-/private/tmp}/xiaolachang-dmg-stage"
DIST="$ROOT/dist"
PYTHON="${PYTHON:-/usr/bin/python3}"

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

write_dmg_background() {
  local output="$1"
  "$PYTHON" - <<'PY' "$output"
import math
import struct
import sys
import zlib
from pathlib import Path

out = Path(sys.argv[1])
width, height = 600, 420
bg = (28, 28, 28, 255)
panel = (42, 42, 42, 255)
line = (112, 112, 112, 255)
accent = (66, 190, 112, 255)
soft = (232, 232, 232, 255)
muted = (130, 130, 130, 255)
pixels = bytearray(bg * width * height)

def put(x, y, color):
    if 0 <= x < width and 0 <= y < height:
        i = (y * width + x) * 4
        pixels[i:i + 4] = bytes(color)

def rect(x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(height, y1)):
        row = (y * width + max(0, x0)) * 4
        pixels[row:row + (min(width, x1) - max(0, x0)) * 4] = bytes(color) * (min(width, x1) - max(0, x0))

def rounded_rect(x0, y0, x1, y1, radius, color):
    for y in range(y0, y1):
        for x in range(x0, x1):
            dx = max(x0 + radius - x, 0, x - (x1 - radius - 1))
            dy = max(y0 + radius - y, 0, y - (y1 - radius - 1))
            if dx * dx + dy * dy <= radius * radius:
                put(x, y, color)

def circle(cx, cy, r, color):
    rr = r * r
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= rr:
                put(x, y, color)

def line_draw(x0, y0, x1, y1, color, thickness=3):
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    for step in range(steps + 1):
        t = step / steps
        x = round(x0 + (x1 - x0) * t)
        y = round(y0 + (y1 - y0) * t)
        circle(x, y, thickness, color)

rounded_rect(28, 28, 572, 392, 24, panel)
rounded_rect(58, 72, 252, 286, 18, (36, 36, 36, 255))
rounded_rect(348, 72, 542, 286, 18, (36, 36, 36, 255))
circle(155, 178, 68, (48, 48, 48, 255))
circle(445, 178, 68, (48, 48, 48, 255))
line_draw(252, 178, 348, 178, accent, 4)
line_draw(328, 156, 350, 178, accent, 4)
line_draw(328, 200, 350, 178, accent, 4)
rect(126, 318, 474, 322, line)
circle(112, 320, 5, muted)
circle(488, 320, 5, muted)

raw = b"".join(b"\x00" + pixels[y * width * 4:(y + 1) * width * 4] for y in range(height))
def chunk(name, data):
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
png = b"\x89PNG\r\n\x1a\n"
png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(raw, 9))
png += chunk(b"IEND", b"")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(png)
PY
}

customize_dmg_window() {
  local dmg="$1"
  local volume_name="$2"
  local mount_point="$3"
  local source_folder="$4"
  rm -rf "$mount_point"
  mkdir -p "$mount_point"
  hdiutil attach "$dmg" -mountpoint "$mount_point" -nobrowse -noverify >/dev/null
  ditto --norsrc "$source_folder" "$mount_point"
  chflags hidden "$mount_point/.background" 2>/dev/null || true
  if ! osascript <<OSA
tell application "Finder"
  set targetFolder to (POSIX file "$mount_point/" as alias)
  open targetFolder
  set win to container window of targetFolder
  set current view of win to icon view
  set toolbar visible of win to false
  set statusbar visible of win to false
  set bounds of win to {120, 120, 720, 540}
  set opts to icon view options of win
  set arrangement of opts to not arranged
  set icon size of opts to 96
  set background picture of opts to (POSIX file "$mount_point/.background/background.png" as alias)
  set position of item "$APP_NAME" of targetFolder to {155, 178}
  set position of item "Applications" of targetFolder to {445, 178}
  set position of item "首次打开说明.txt" of targetFolder to {300, 335}
  update targetFolder without registering applications
  delay 1
  close win
end tell
OSA
  then
    echo "Warning: Finder DMG layout customization failed; continuing with packaged DMG." >&2
  fi
  sync
  hdiutil detach "$mount_point" >/dev/null || hdiutil detach "$mount_point" -force >/dev/null
}

APP="$APP" SIGNED_APP="$SIGNED_APP" "$MAC_DIR/build_control_app.command"

VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"
DMG_NAME="XiaoLaChang-${VERSION}-mac.dmg"
VOLNAME="小腊肠 $VERSION"
DMG_RW="$BUILD_DIR/${DMG_NAME%.dmg}.rw.dmg"
DMG_TMP="$BUILD_DIR/${DMG_NAME%.dmg}.tmp.dmg"
DMG="$DIST/$DMG_NAME"
MOUNT_POINT="$BUILD_DIR/dmg-mount"

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
mkdir -p "$STAGE/.background"
write_dmg_background "$STAGE/.background/background.png"
chflags hidden "$STAGE/.background" 2>/dev/null || true

cat > "$STAGE/首次打开说明.txt" <<'TXT'
小腊肠首次打开说明

1. 把 XiaoLaChang.app 拖到 Applications。App 打开后显示名仍是“小腊肠”。
2. 如果 macOS 提示“无法验证开发者”，请右键点击 App，选择“打开”，再在弹窗中确认。
3. 如果仍被拦截，进入“系统设置” -> “隐私与安全性”，允许打开小腊肠。
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

rm -f "$DMG_RW" "$DMG_TMP" "$DMG"
DMG_SIZE_MB="$(du -sm "$STAGE" | awk '{print $1}')"
DMG_SIZE_MB="$((DMG_SIZE_MB + 128))"
hdiutil create \
  -volname "$VOLNAME" \
  -fs HFS+ \
  -size "${DMG_SIZE_MB}m" \
  -ov \
  "$DMG_RW"
customize_dmg_window "$DMG_RW" "$VOLNAME" "$MOUNT_POINT" "$STAGE"
hdiutil convert "$DMG_RW" -format UDZO -o "$DMG_TMP" -ov
hdiutil verify "$DMG_TMP"
mv "$DMG_TMP" "$DMG"
rm -f "$DMG_RW"
rm -rf "$MOUNT_POINT"
xattr -cr "$DMG"

echo "Built DMG: $DMG"
