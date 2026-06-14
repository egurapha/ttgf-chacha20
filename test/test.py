# SPDX-FileCopyrightText: © 2026 Raphael Eguchi
# SPDX-License-Identifier: Apache-2.0
"""Tiny Tapeout full-chip test (Makefile flow: tb.v + this module).

Drives only the real pins of tt_um_egurapha_chacha20 — RX on ui_in[3], TX on
uo_out[4] — over a bit-level serial link, and checks streamed keystream against
the reference. This is the test the TT `top-level` CI job and gate-level
sign-off (`make GATES=yes`) run against the hardened netlist.

It runs at the silicon BAUD_DIV (434), which the netlist bakes in, so it is a
focused smoke test (load config + GEN, verify a keystream prefix) rather than
the exhaustive suite — that lives in test/unit/ (the `unit` CI job).
"""

import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

sys.path.insert(0, os.path.dirname(__file__))  # make chacha20_ref importable
import chacha20_ref

BAUD_DIV = 434  # silicon default (baked into the gate-level netlist)
RX_BIT = 3  # ui_in[3]
TX_BIT = 4  # uo_out[4]

CMD_LOAD_KEY = 0x01
CMD_LOAD_NONCE = 0x02
CMD_LOAD_CTR = 0x03
CMD_GEN = 0x04

CHECK_BYTES = 16  # keystream prefix to verify (keeps gate-level sim tractable)


def _tx(dut):
    return (int(dut.uo_out.value) >> TX_BIT) & 1


async def serial_send_byte(dut, value):
    """Shift one byte onto RX at BAUD_DIV: start, 8 data LSB-first, stop."""
    dut.ui_in.value = 0  # start bit (RX_BIT low)
    await ClockCycles(dut.clk, BAUD_DIV)
    for i in range(8):
        dut.ui_in.value = ((value >> i) & 1) << RX_BIT
        await ClockCycles(dut.clk, BAUD_DIV)
    dut.ui_in.value = 1 << RX_BIT  # stop bit / idle high
    await ClockCycles(dut.clk, BAUD_DIV)


async def serial_send_frame(dut, cmd, payload):
    await serial_send_byte(dut, cmd)
    for b in payload:
        await serial_send_byte(dut, b)


def tx_monitor(dut, sink):
    async def _run():
        while True:
            while _tx(dut) == 1:  # wait for a start bit
                await RisingEdge(dut.clk)
            await ClockCycles(dut.clk, BAUD_DIV + BAUD_DIV // 2)  # centre of bit 0
            byte = 0
            for i in range(8):
                byte |= _tx(dut) << i
                await ClockCycles(dut.clk, BAUD_DIV)
            sink.append(byte)

    return cocotb.start_soon(_run())


@cocotb.test()
async def full_chip_gen(dut):
    """Load key/nonce/counter + GEN over the serial pins; verify keystream prefix."""
    clock = Clock(dut.clk, 20, unit="ns")  # 50 MHz (matches BAUD_DIV=434)
    cocotb.start_soon(clock.start())

    # Reset; RX idles high.
    dut.ena.value = 1
    dut.ui_in.value = 1 << RX_BIT
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)

    key = bytes(range(32))
    nonce = bytes(range(12))
    counter = 1

    received = []
    tx_monitor(dut, received)

    await serial_send_frame(dut, CMD_LOAD_KEY, key)
    await serial_send_frame(dut, CMD_LOAD_NONCE, nonce)
    await serial_send_frame(dut, CMD_LOAD_CTR, counter.to_bytes(4, "little"))
    await serial_send_frame(dut, CMD_GEN, bytes([1]))

    # Wait until enough keystream bytes have been received.
    timeout = 0
    while len(received) < CHECK_BYTES and timeout < 2_000_000:
        await RisingEdge(dut.clk)
        timeout += 1

    exp = chacha20_ref.chacha20_block(key, counter, nonce)[:CHECK_BYTES]
    got = bytes(received[:CHECK_BYTES])
    assert got == exp, f"full-chip GEN mismatch:\n  got={got.hex()}\n  exp={exp.hex()}"
    dut._log.info(f"full-chip GEN OK: first {CHECK_BYTES} keystream bytes match")
