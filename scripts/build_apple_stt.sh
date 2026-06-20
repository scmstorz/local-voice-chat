#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT_DIR/bin" /tmp/swift-module-cache

swiftc \
  -O \
  -module-cache-path /tmp/swift-module-cache \
  "$ROOT_DIR/tools/apple_stt.swift" \
  -o "$ROOT_DIR/bin/apple_stt"

swiftc \
  -O \
  -module-cache-path /tmp/swift-module-cache \
  "$ROOT_DIR/tools/apple_live_stt.swift" \
  -o "$ROOT_DIR/bin/apple_live_stt"

echo "$ROOT_DIR/bin/apple_stt"
echo "$ROOT_DIR/bin/apple_live_stt"
