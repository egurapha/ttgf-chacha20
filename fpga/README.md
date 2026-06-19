# FPGA bring-up

Host tooling to run and exercise the ChaCha20 design on the **Tiny Tapeout FPGA
breakout**: a FabricFox iCE40 UP5K on a demoboard whose RP2350 runs the Tiny
Tapeout MicroPython SDK.

The FPGA is a **functional rig**: it runs at ~10 MHz and validates behavior, not
ASIC timing. Bitstream artifacts live in [`../fpga_artifact/`](../fpga_artifact).

## Contents

| Path | Purpose |
|------|---------|
| `flash_rp_firmware.sh` | Flash the RP2350 demoboard firmware (UF2 via BOOTSEL). |
| `flash_chacha20.sh` | Load the bitstream onto the iCE40 and verify a clean reset. |
| `fpga_test.sh`, `fpga_test_suite.py` | Functional suite over both interfaces, checked against `../test/chacha20_ref.py`. |
| `python/` | Host-side Python interface: encrypt/decrypt and read keystream over UART. |

## Setup (once)

```sh
python3 -m venv ~/.ttfpga-venv && ~/.ttfpga-venv/bin/pip install mpremote
```

The serial port (`/dev/ttyACM0`) is root-owned, so add yourself to the `uucp` group
(`sudo usermod -aG uucp $USER`, then re-login), or the scripts fall back to `sudo`.
The board must run FPGA-capable firmware (v3.0.x); `flash_rp_firmware.sh` installs it.

## Workflow

```sh
./flash_rp_firmware.sh   # 1. firmware, once (enter BOOTSEL first: hold BOOT, replug)
./flash_chacha20.sh      # 2. load bitstream + idle check
./fpga_test.sh           # 3. functional suite -> "SUITE RESULT: PASS"
```

## Python interface

`python/chacha20_fpga.py` exposes a `ChaCha20FPGA` class driven over the chip's UART:

```python
from chacha20_fpga import ChaCha20FPGA

c = ChaCha20FPGA().connect()           # programs the bitstream on first use
ct = c.encrypt(key, nonce, b"hello")   # key = 32 bytes, nonce = 12 bytes
pt = c.decrypt(key, nonce, ct)         # symmetric: decrypt == encrypt
ks = c.keystream(key, nonce, 64)
```

`python/example.py` is a runnable encrypt/decrypt round-trip demo:

```sh
~/.ttfpga-venv/bin/python python/example.py
```

## Notes

- Every interface is driven by single-step clocking (the host generates each
  project-clock edge), so operations are deterministic on any board. UART is
  correct but slow (~200 clocks/bit), suited to messages rather than bulk throughput.
- Test expected values come from `../test/chacha20_ref.py`, the same reference the
  cocotb suite checks against.
