#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/out/t20_android81_stock.config}"
EXPECTED="2b4565a303190682de2a2fe58f13cd3a68e81ce142c308d899cd2526a0d72442"

mkdir -p "$(dirname "$OUT")"
cat "$ROOT"/stock/config_chunks/part*.b64 \
  | tr -d '\r\n' \
  | base64 -d \
  | gzip -dc > "$OUT"

ACTUAL="$(sha256sum "$OUT" | awk '{print $1}')"
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  echo "ERROR: stock config SHA256 mismatch" >&2
  echo "expected: $EXPECTED" >&2
  echo "actual:   $ACTUAL" >&2
  exit 2
fi

echo "Stock config OK: $ACTUAL"
