# SPDX-FileCopyrightText: © 2026 Raphael Eguchi
# SPDX-License-Identifier: Apache-2.0
"""Tiny Tapeout full-chip test (Makefile flow: tb.v + this module).

Two GEN smoke tests against the hardened netlist, one per interface:
  * full_chip_gen: UART path (RX=ui_in[3], TX=uo_out[4]), bit-serial.
  * full_chip_parallel_gen: parallel byte bus (MODE=uio[3]=1, WR/VALID handshake).
Each loads key/nonce/counter + GEN and checks a keystream prefix vs chacha20_ref.
This is what the TT `top-level` CI job and gate-level sign-off (`make GATES=yes`)
run against the hardened netlist; the exhaustive suite lives in test/unit/.

The UART path uses the silicon BAUD_DIV (200), baked into the netlist.
"""

import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

sys.path.insert(0, os.path.dirname(__file__))  # make chacha20_ref importable
import chacha20_ref

BAUD_DIV = 200  # silicon default (23 MHz / 115200; baked into the gate-level netlist)
RX_BIT = 3  # ui_in[3]
TX_BIT = 4  # uo_out[4]

CMD_LOAD_KEY = 0x01
CMD_LOAD_NONCE = 0x02
CMD_LOAD_CTR = 0x03
CMD_GEN = 0x04

CHECK_BYTES = 16  # keystream prefix to verify (keeps gate-level sim tractable)

# Parallel-interface pins (MODE=uio[3]=1 selects it; see full_chip_parallel_gen).
MODE_BIT = 3
WR_BIT = 0
VALID_BIT = 1     # uio_out[1] = output valid
HOLD_SEL = 1      # uio[5:4] -> output held 2 cycles
PAR_GAP = 8       # idle cycles between parallel bytes (covers controller settle)


def _tx(dut):
    # Gate-level sim leaves uo_out with X bits right after reset (cells settle a
    # cycle later than RTL). Tolerate that: an unresolved bus reads as idle-high
    # (1), so the monitor waits through the startup-X window.
    try:
        return (int(dut.uo_out.value) >> TX_BIT) & 1
    except ValueError:
        return 1


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
    # Testbench clock, not the silicon clock. The gate-level netlist uses
    # unit-delay cell models (-DUNIT_DELAY=#1, ~1ns/cell), so the period must
    # exceed the worst combinational depth (~20 cells) for paths to settle.
    clock = Clock(dut.clk, 100, unit="ns")
    cocotb.start_soon(clock.start())

    # Reset; RX idles high.
    dut.ena.value = 1
    dut.ui_in.value = 1 << RX_BIT
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)

    # Optional debug probe (disabled): logs the control pins (busy/err/tx) on
    # every change. Uncomment to trace control flow at the gate level.
    # async def _diag():
    #     cyc = 0
    #     prev = None
    #     while True:
    #         await RisingEdge(dut.clk)
    #         cyc += 1
    #         try:
    #             v = int(dut.uo_out.value)
    #             tag = f"uo_out={v:08b} busy={v & 1} err={(v >> 1) & 1} tx={(v >> 4) & 1}"
    #         except ValueError:
    #             tag = f"uo_out=X (raw={dut.uo_out.value})"
    #         if tag != prev:
    #             dut._log.info(f"[diag] cyc={cyc} {tag}")
    #             prev = tag
    #
    # cocotb.start_soon(_diag())

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


def _par_uio(wr):
    return (1 << MODE_BIT) | (HOLD_SEL << 4) | (wr << WR_BIT)


def _par_valid(dut):
    # uio_out[VALID_BIT], tolerating gate-level startup X (treated as not-valid).
    try:
        return (int(dut.uio_out.value) >> VALID_BIT) & 1
    except ValueError:
        return 0


async def par_send_byte(dut, value):
    dut.ui_in.value = value
    dut.uio_in.value = _par_uio(wr=1)
    await RisingEdge(dut.clk)
    dut.uio_in.value = _par_uio(wr=0)
    dut.ui_in.value = 0
    await ClockCycles(dut.clk, PAR_GAP)


async def par_send_frame(dut, cmd, payload):
    await par_send_byte(dut, cmd)
    for b in payload:
        await par_send_byte(dut, b)


@cocotb.test()
async def full_chip_parallel_gen(dut):
    """GEN smoke test over the PARALLEL interface (MODE=1) on the hardened netlist.

    Confirms the parallel front-end survives synthesis (no gate-level X-hang) and
    streams correct keystream; the parallel analogue of full_chip_gen.
    """
    cocotb.start_soon(Clock(dut.clk, 100, unit="ns").start())

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = _par_uio(wr=0)  # MODE=1, WR=0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)

    key = bytes(range(32))
    nonce = bytes(range(12))
    counter = 1

    await par_send_frame(dut, CMD_LOAD_KEY, key)
    await par_send_frame(dut, CMD_LOAD_NONCE, nonce)
    await par_send_frame(dut, CMD_LOAD_CTR, counter.to_bytes(4, "little"))
    await par_send_frame(dut, CMD_GEN, bytes([1]))

    received = []
    prev_v = 0
    timeout = 0
    while len(received) < CHECK_BYTES and timeout < 2_000_000:
        await RisingEdge(dut.clk)
        v = _par_valid(dut)
        if v == 1 and prev_v == 0:  # rising edge of VALID
            try:
                received.append(int(dut.uo_out.value) & 0xFF)
            except ValueError:
                pass  # X data at startup -> skip (shouldn't occur once streaming)
        prev_v = v
        timeout += 1

    exp = chacha20_ref.chacha20_block(key, counter, nonce)[:CHECK_BYTES]
    got = bytes(received[:CHECK_BYTES])
    assert got == exp, f"parallel GEN mismatch:\n  got={got.hex()}\n  exp={exp.hex()}"
    dut._log.info(f"parallel GEN OK: first {CHECK_BYTES} keystream bytes match")
