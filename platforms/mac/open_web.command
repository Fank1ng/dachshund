#!/bin/zsh
set -e

MAC_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$MAC_DIR/setup_proxy.command"
