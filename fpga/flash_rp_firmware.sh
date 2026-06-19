#!/usr/bin/env bash
#
# flash_rp_firmware.sh -- flash the Tiny Tapeout demoboard RP2350 firmware.
#
# We needed the FPGA-breakout-capable firmware (v3.0.x adds the FabricFox
# /bitstreams loader). The board shipped with older ASIC-only firmware whose
# tt.shuttle could not see /bitstreams, so tt.shuttle.<proj>.enable() failed.
#
# Flashing the RP is a UF2 drag-and-drop to the BOOTSEL drive -- NOT how the
# iCE40 bitstream is loaded (that's flash_chacha20.sh, over serial).
#
# Procedure:
#   1. Put the board in BOOTSEL: HOLD the BOOT button, replug USB, release BOOT.
#      A FAT drive labelled "RP2350" mounts (here: /run/media/$USER/RP2350).
#   2. Run this script. It downloads the firmware UF2 (cached in ~) and copies
#      it onto that drive. The board reflashes and reboots into MicroPython.
#   3. The littlefs filesystem (incl. /bitstreams) survives the update.
#
# After this, run flash_chacha20.sh to load the design, then fpga_test.sh.
set -uo pipefail

FW_VER="v3.0.7"
FW_FILE="tt-demo-rp2350-${FW_VER}.uf2"
FW_URL="https://github.com/TinyTapeout/tt-micropython-firmware/releases/download/${FW_VER}/${FW_FILE}"
FW_LOCAL="$HOME/${FW_FILE}"

# 1) Get the firmware UF2 (cache in home dir).
if [ ! -f "$FW_LOCAL" ]; then
    echo "Downloading $FW_FILE ..."
    curl -sL -o "$FW_LOCAL" "$FW_URL" || { echo "ERROR: download failed"; exit 1; }
fi
# Sanity: UF2 magic is "UF2\n".
if [ "$(head -c 3 "$FW_LOCAL")" != "UF2" ]; then
    echo "ERROR: $FW_LOCAL is not a valid UF2 (re-download?)"; exit 1
fi
echo "firmware: $FW_LOCAL ($(stat -c%s "$FW_LOCAL") bytes)"

# 2) Find the BOOTSEL drive.
MNT="$(grep -i RP2350 /proc/mounts | awk '{print $2}' | head -1)"
if [ -z "$MNT" ] || [ ! -w "$MNT" ]; then
    echo
    echo "No writable RP2350 BOOTSEL drive found."
    echo "Enter BOOTSEL first: HOLD the BOOT button, replug USB, release BOOT,"
    echo "wait for the 'RP2350' drive to mount, then re-run this script."
    exit 1
fi
echo "BOOTSEL drive: $MNT"

# 3) Copy the UF2 -> board reflashes and reboots automatically.
echo "Flashing (the board will reboot on its own when done)..."
cp "$FW_LOCAL" "$MNT/" && sync
echo "Done. Wait a few seconds, then check for /dev/ttyACM0 (MicroPython mode)."
