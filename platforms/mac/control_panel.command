#!/bin/zsh
set -u

MAC_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$MAC_DIR/../.." && pwd)"
exec "$ROOT/小腊肠.app/Contents/MacOS/小腊肠"
