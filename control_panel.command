#!/bin/zsh
set -u

cd "$(dirname "$0")" || exit 1
exec "./Codex Proxy Control.app/Contents/MacOS/Codex Proxy Control"
