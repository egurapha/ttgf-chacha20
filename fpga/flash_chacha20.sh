#!/usr/bin/env bash
#
# flash_chacha20.sh -- load the ChaCha20 iCE40 bitstream onto the Tiny Tapeout
# FPGA breakout (demoboard RP2350 running the TT MicroPython SDK) and do a quick
# liveness check.
#
# The board must be in NORMAL MicroPython mode (NOT BOOTSEL). If you see a drive
# named "RP2350" mounted, you're in BOOTSEL: unplug/replug WITHOUT holding BOOT.
#
# Serial port is owned by root:uucp and you're not in that group, so the
# mpremote calls run under sudo (you'll be asked for your password once).

set -euo pipefail

# ---- Config (edit if needed) -------------------------------------------------
PORT="/dev/ttyACM0"
NAME="tt_um_egurapha_chacha20"
# This script lives in <repo>/fpga; the FPGA build artifacts are in
# <repo>/fpga_artifact (the bitstream downloaded from the `fpga` CI workflow).
REPO="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$REPO/fpga_artifact/build/${NAME}.bin"
MPREMOTE="$HOME/.ttfpga-venv/bin/mpremote"
# Project clock. The bitstream closes timing at ~12.66 MHz; 10 MHz is a safe
# functional-bring-up rate and divides cleanly from the RP2350's 150 MHz.
CLK_HZ=10000000
# ------------------------------------------------------------------------------

MP() { sudo "$MPREMOTE" connect "$PORT" "$@"; }

echo "== Pre-flight ================================================="
[ -x "$MPREMOTE" ] || { echo "ERROR: mpremote not found at $MPREMOTE"; exit 1; }
[ -f "$BIN" ]      || { echo "ERROR: bitstream not found: $BIN"; exit 1; }

if mount | grep -qi 'RP2350'; then
    echo "ERROR: board is in BOOTSEL (RP2350 drive is mounted)."
    echo "       Unplug/replug the USB WITHOUT holding BOOT, then re-run."
    exit 1
fi
if [ ! -e "$PORT" ]; then
    echo "ERROR: $PORT not present. Is the board in MicroPython mode?"
    exit 1
fi
echo "  bitstream : $BIN ($(stat -c%s "$BIN") bytes)"
echo "  port      : $PORT"
echo "  clock     : $CLK_HZ Hz"

echo "== Sanity: FPGA carrier detected? ============================="
MP exec "
from ttboard.boot.demoboard_detect import DemoboardDetect, DemoboardCarrier
ok = DemoboardDetect.probe()
print('probe:', ok, ' CarrierVersion:', DemoboardDetect.CarrierVersion, '(FPGA ==', DemoboardCarrier.FPGA, ')')
if DemoboardDetect.CarrierVersion != DemoboardCarrier.FPGA:
    print('WARNING: FPGA carrier NOT detected -- is the FabricFox seated?')
"

echo "== Upload bitstream to /bitstreams/ ==========================="
MP fs mkdir :/bitstreams 2>/dev/null || true   # ignore "already exists"
MP fs cp "$BIN" ":/bitstreams/${NAME}.bin"
echo "  contents of /bitstreams:"
MP fs ls :/bitstreams

echo "== Load (enable) the bitstream + clock + reset + read ========="
MP exec "
import ttboard.util.time as time
# Probe for the FPGA carrier BEFORE building the board, so the SDK comes up in
# FPGA mode (tt.shuttle = the FPGA mux that scans /bitstreams). This is the step
# the stock main.py does at power-up; doing it here makes the run self-contained.
from ttboard.boot.demoboard_detect import DemoboardDetect, DemoboardCarrier
DemoboardDetect.probe()
# Clear any stale ASIC-mode singletons so the board is rebuilt fresh in FPGA mode.
from ttboard.demoboard import DemoBoard
from ttboard.globals import Globals
DemoBoard._DemoBoardSingleton_Instance = None
Globals.Pins_Singleton = None
Globals.ProjectMux_Singleton = None
tt = DemoBoard.get()
print('mode:', tt.mode if hasattr(tt,'mode') else '?', ' shuttle:', tt.shuttle)
# Program the iCE40 with our bitstream.
proj = getattr(tt.shuttle, '${NAME}')
proj.enable()                     # spi_transferPIO streams the .bin into the FPGA
print('enabled:', tt.shuttle.enabled)
# Clock + reset + read idle status.
tt.clock_project_PWM(${CLK_HZ})
time.sleep_ms(5)
# Hold inputs at a clean UART idle: RX (ui[3]) HIGH so the receiver doesn't frame
# noise into a bogus command (which would latch ERR). MODE (uio[3]) low = UART.
tt.ui_in.value = 0x08
time.sleep_ms(1)
tt.reset_project(True); time.sleep_ms(5); tt.reset_project(False); time.sleep_ms(5)
uo = int(tt.uo_out.value)
print('uo_out=', hex(uo), '  BUSY(uo0)=', uo & 1, ' ERR(uo1)=', (uo>>1) & 1)
print('IDLE CHECK:', 'PASS (BUSY=0, ERR=0)' if (uo & 0x3)==0 else 'unexpected: '+hex(uo))
"

echo "== Done. Bitstream is loaded and clocked. ====================="
