#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="$ROOT_DIR/dist/electron"
APP_DIR="$OUT_DIR/linux-unpacked"
ICON="$ROOT_DIR/src/core/static/icons/icon-512.png"

if [[ ! -d "$APP_DIR" ]]; then
  echo "Missing Electron output: $APP_DIR" >&2
  echo "Run electron-builder --linux dir before building the RPM." >&2
  exit 1
fi

if ! command -v rpmbuild >/dev/null 2>&1; then
  echo "rpmbuild is required. Install it with: sudo dnf install rpm-build" >&2
  exit 1
fi

PKG_NAME="dachshund"
PRODUCT_NAME="Dachshund"
VERSION="$(node -p "require('./package.json').version")"
SUMMARY="$(node -p "require('./package.json').build.linux.synopsis || require('./package.json').description")"
DESCRIPTION="$(node -p "require('./package.json').description")"
RPM_ARCH="x86_64"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/dachshund-rpm.XXXXXX")"
STAGE_DIR="$WORK_DIR/stage"
BUILDROOT_DIR="$WORK_DIR/buildroot"
RPMBUILD_DIR="$WORK_DIR/rpmbuild"
SPEC_FILE="$RPMBUILD_DIR/SPECS/$PKG_NAME.spec"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

mkdir -p \
  "$STAGE_DIR/opt/$PRODUCT_NAME" \
  "$STAGE_DIR/usr/bin" \
  "$STAGE_DIR/usr/share/applications" \
  "$STAGE_DIR/usr/share/icons/hicolor/512x512/apps" \
  "$WORK_DIR/tmp" \
  "$RPMBUILD_DIR/BUILD" \
  "$RPMBUILD_DIR/RPMS" \
  "$RPMBUILD_DIR/SOURCES" \
  "$RPMBUILD_DIR/SPECS" \
  "$RPMBUILD_DIR/SRPMS"

cp -a "$APP_DIR/." "$STAGE_DIR/opt/$PRODUCT_NAME/"
cp "$ICON" "$STAGE_DIR/usr/share/icons/hicolor/512x512/apps/$PKG_NAME.png"

cat >"$STAGE_DIR/usr/bin/dachshund" <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail

REAL_DACHSHUND="/opt/Dachshund/dachshund"
RUNTIME_ROOT="/opt/Dachshund/resources/runtime"
NATIVE_MENU="$RUNTIME_ROOT/platforms/linux/native_menu.py"
SESSION_TYPE="${XDG_SESSION_TYPE:-}"
DESKTOPS="${XDG_CURRENT_DESKTOP:-}:${XDG_SESSION_DESKTOP:-}"
lower_session="$(printf '%s' "$SESSION_TYPE" | tr '[:upper:]' '[:lower:]')"
lower_desktops="$(printf '%s' "$DESKTOPS" | tr '[:upper:]' '[:lower:]')"

is_kde_wayland() {
  [[ "${DACHSHUND_KDE_WAYLAND:-}" == "1" ]] && return 0
  [[ "${DACHSHUND_NATIVE_WAYLAND:-}" == "1" ]] && return 1
  [[ "$lower_session" == "wayland" ]] \
    && [[ "$lower_desktops" =~ (^|[[:space:]:;])(kde|plasma)([[:space:]:;]|$) ]]
}

kde_helper_env() {
  export DACHSHUND_KDE_WAYLAND=1
  export CODEX_PROXY_SOURCE_DIR="$RUNTIME_ROOT"
  export CODEX_PROXY_APP_EXECUTABLE="/usr/bin/dachshund"
}

native_wayland_env() {
  kde_helper_env
  export ELECTRON_OZONE_PLATFORM_HINT=wayland
}

xwayland_env() {
  kde_helper_env
  export GDK_BACKEND=x11
  export ELECTRON_OZONE_PLATFORM_HINT=x11
  unset WAYLAND_DISPLAY
  unset WAYLAND_SOCKET
  export XDG_SESSION_TYPE=x11
  export DESKTOP_SESSION=plasma
}

start_native_menu() {
  [[ -f "$NATIVE_MENU" ]] || return 0
  if command -v python3 >/dev/null 2>&1; then
    nohup python3 "$NATIVE_MENU" >/tmp/dachshund-native-menu.log 2>&1 &
  fi
}

case "${1:-}" in
  --quit)
    exec "$REAL_DACHSHUND" "$@"
    ;;
  --native-menu-helper)
    shift
    kde_helper_env
    exec python3 "$NATIVE_MENU" "$@"
    ;;
  --tray)
    shift
    kde_helper_env
    exec python3 "$NATIVE_MENU" "$@"
    ;;
esac

if [[ "${DACHSHUND_NATIVE_WAYLAND:-}" != "1" ]] \
  && is_kde_wayland; then
  native_wayland_env
  start_native_menu
  if [[ "${DACHSHUND_FORCE_XWAYLAND:-}" == "1" ]]; then
    xwayland_env
    exec "$REAL_DACHSHUND" --ozone-platform=x11 "$@"
  fi
  exec "$REAL_DACHSHUND" --ozone-platform=wayland "$@"
fi

exec "$REAL_DACHSHUND" "$@"
WRAPPER
chmod 0755 "$STAGE_DIR/usr/bin/dachshund"

cat >"$STAGE_DIR/usr/share/applications/$PKG_NAME.desktop" <<DESKTOP
[Desktop Entry]
Name=$PRODUCT_NAME
Comment=Local Codex account pool proxy control center
Exec=dachshund %U
Icon=$PKG_NAME
Terminal=false
Type=Application
Categories=Utility;
StartupWMClass=$PRODUCT_NAME
DESKTOP

cat >"$SPEC_FILE" <<SPEC
Name:           $PKG_NAME
Version:        $VERSION
Release:        1%{?dist}
Summary:        $SUMMARY
License:        MIT
URL:            https://github.com/Fank1ng/dachshund
BuildArch:      $RPM_ARCH
Requires:       python3
Requires:       python3-aiohttp
Requires:       python3-gobject
Requires:       systemd
Requires:       xdg-utils

%description
$DESCRIPTION

%install
mkdir -p %{buildroot}
cp -a $STAGE_DIR/. %{buildroot}/

%files
/opt/$PRODUCT_NAME
/usr/bin/dachshund
/usr/share/applications/$PKG_NAME.desktop
/usr/share/icons/hicolor/512x512/apps/$PKG_NAME.png

%changelog
* Wed Jun 24 2026 fank1ng <fank1ng@users.noreply.github.com> - $VERSION-1
- Build Fedora RPM package for Dachshund.
SPEC

rpmbuild \
  --define "_topdir $RPMBUILD_DIR" \
  --define "_tmppath $WORK_DIR/tmp" \
  --define "_build_id_links none" \
  --buildroot "$BUILDROOT_DIR" \
  -bb "$SPEC_FILE"

RPM_PATH="$(find "$RPMBUILD_DIR/RPMS/$RPM_ARCH" -maxdepth 1 -type f -name "$PKG_NAME-$VERSION-1*.rpm" | sort | tail -n 1)"
if [[ -z "$RPM_PATH" ]]; then
  echo "RPM was not produced under $RPMBUILD_DIR/RPMS/$RPM_ARCH" >&2
  exit 1
fi
TARGET_PATH="$OUT_DIR/$PRODUCT_NAME-$VERSION-linux-$RPM_ARCH.rpm"
cp "$RPM_PATH" "$TARGET_PATH"
echo "Built $TARGET_PATH"
