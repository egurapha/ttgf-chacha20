#!/usr/bin/env python3
"""Encrypt and decrypt a message on the ChaCha20 FPGA over UART.

Run with the venv Python so mpremote resolves, e.g.:
    ~/.ttfpga-venv/bin/python example.py
(If /dev/ttyACM0 isn't accessible to your user, it falls back to sudo.)
"""

import os

from chacha20_fpga import ChaCha20FPGA

key = os.urandom(32)  # 256-bit key
nonce = os.urandom(12)  # 96-bit nonce
message = b"Hello from the ChaCha20 FPGA!"

c = ChaCha20FPGA().connect()  # programs the bitstream on first connect

ciphertext = c.encrypt(key, nonce, message)
recovered = c.decrypt(key, nonce, ciphertext)  # same op, recovers plaintext

print("key       :", key.hex())
print("nonce     :", nonce.hex())
print("message   :", message)
print("ciphertext:", ciphertext.hex())
print("recovered :", recovered)
print("round-trip:", "OK" if recovered == message else "MISMATCH")
