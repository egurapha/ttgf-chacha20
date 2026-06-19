#!/usr/bin/env bash
# Run the full ChaCha20 functional suite on the TT FPGA breakout.
# Tests BOTH interfaces (parallel + UART) with GEN / multiblock GEN / CRYPT /
# CRYPT roundtrip / bad-command, all checked on-board against the repo reference
# (test/chacha20_ref.py) -- the same model the cocotb suite uses.
set -uo pipefail
PORT="/dev/ttyACM0"
HERE="$(cd "$(dirname "$0")" && pwd)"   # <repo>/fpga
REPO="$(dirname "$HERE")"               # <repo>
MPREMOTE="$HOME/.ttfpga-venv/bin/mpremote"
MP() { sudo "$MPREMOTE" connect "$PORT" "$@"; }

[ -e "$PORT" ] || { echo "ERROR: $PORT not present (board in MicroPython mode?)"; exit 1; }
if mount | grep -qi 'RP2350'; then echo "ERROR: board is in BOOTSEL; replug without BOOT."; exit 1; fi

# Push the reference model (single source of truth) and the bitstream to the board.
MP fs mkdir :/lib 2>/dev/null || true
MP fs cp "$REPO/test/chacha20_ref.py" :/lib/chacha20_ref.py
MP fs mkdir :/bitstreams 2>/dev/null || true
MP fs cp "$REPO/fpga_artifact/build/tt_um_egurapha_chacha20.bin" \
         :/bitstreams/tt_um_egurapha_chacha20.bin

echo "== Running full functional suite (parallel + UART) =="
OUT="$(MP run "$HERE/fpga_test_suite.py")"
echo "$OUT"
echo "$OUT" | grep -q "SUITE RESULT: PASS"
