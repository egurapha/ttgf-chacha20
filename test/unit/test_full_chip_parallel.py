# SPDX-FileCopyrightText: © 2026 Raphael Eguchi
# SPDX-License-Identifier: Apache-2.0
"""Full-chip test over the PARALLEL byte interface (MODE = 1).

Drives the parallel front-end the way a host does, following the byte protocol:
  * MODE pin (uio[3]) = 1 selects the parallel interface.
  * Send a byte: put it on ui_in[7:0], pulse WR (uio[0]) high for one cycle.
  * Read a byte: watch VALID (uio_out[1]); read uo_out[7:0] on its RISING edge
    (VALID is held hold_sel+1 cycles, so read once per burst).
  * Between frames, wait for BUSY (uio_out[2]) to go low before the next command.

Tests both command paths (GEN keystream, CRYPT encrypt/decrypt round-trip),
scoreboarded against chacha20_ref.

Run from the test/ directory:
    ./run_unit_tests.sh -k full_chip_parallel
"""

import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

import chacha20_ref

CMD_LOAD_KEY = 0x01
CMD_LOAD_NONCE = 0x02
CMD_LOAD_CTR = 0x03
CMD_GEN = 0x04
CMD_CRYPT = 0x05

MODE_BIT = 3       # uio[3] = 1 -> parallel interface active
WR_BIT = 0         # uio[0]  = write strobe (host -> chip)
VALID_BIT = 1      # uio_out[1] = output valid (chip -> host)
BUSY_BIT = 2       # uio_out[2] = controller busy (high while fsm != IDLE)
HOLD_SEL = 1       # uio[5:4]; output held HOLD_SEL+1 = 2 cycles
GAP = 2            # idle cycles between input bytes (within a frame)
CORE_WAIT = 120    # cycles to let the core compute a block before CRYPT plaintext


def _uio(wr: int, hold: int = HOLD_SEL) -> int:
    return (1 << MODE_BIT) | ((hold & 0x3) << 4) | (wr << WR_BIT)


async def reset(dut, hold: int = HOLD_SEL):
    dut.ui_in.value = 0
    dut.uio_in.value = _uio(wr=0, hold=hold)
    dut.ena.value = 1
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


def _busy(dut) -> int:
    return (int(dut.uio_out.value) >> BUSY_BIT) & 1


async def wait_busy_low(dut, timeout: int = 10_000):
    w = 0
    while w < timeout:
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        if _busy(dut) == 0:
            return
        w += 1
    raise TimeoutError("BUSY stuck high")


async def send_byte(dut, value: int, hold: int = HOLD_SEL):
    dut.ui_in.value = value
    dut.uio_in.value = _uio(wr=1, hold=hold)
    await RisingEdge(dut.clk)        # captured on this edge
    dut.uio_in.value = _uio(wr=0, hold=hold)
    dut.ui_in.value = 0
    await ClockCycles(dut.clk, GAP)


async def send_frame(dut, cmd: int, payload: bytes, hold: int = HOLD_SEL):
    await send_byte(dut, cmd, hold)
    for b in payload:
        await send_byte(dut, b, hold)


async def read_one(dut, timeout: int = 10_000) -> int:
    """Wait for VALID's rising edge and return the output byte."""
    prev_v = 0
    w = 0
    while w < timeout:
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        v = (int(dut.uio_out.value) >> VALID_BIT) & 1
        if v == 1 and prev_v == 0:
            return int(dut.uo_out.value) & 0xFF
        prev_v = v
        w += 1
    raise TimeoutError("no output byte (VALID never rose)")


async def read_bytes(dut, n: int, timeout: int = 300_000) -> bytes:
    out = []
    prev_v = 0
    w = 0
    while len(out) < n and w < timeout:
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        v = (int(dut.uio_out.value) >> VALID_BIT) & 1
        if v == 1 and prev_v == 0:
            out.append(int(dut.uo_out.value) & 0xFF)
        prev_v = v
        w += 1
    return bytes(out)


async def load_config(dut, key: bytes, counter: int, nonce: bytes, hold: int = HOLD_SEL):
    """Load key/nonce/counter, waiting for BUSY low between frames (the protocol)."""
    await send_frame(dut, CMD_LOAD_KEY, key, hold)
    await wait_busy_low(dut)
    await send_frame(dut, CMD_LOAD_NONCE, nonce, hold)
    await wait_busy_low(dut)
    await send_frame(dut, CMD_LOAD_CTR, counter.to_bytes(4, "little"), hold)
    await wait_busy_low(dut)


@cocotb.test()
async def parallel_gen(dut):
    """GEN keystream over the parallel bus; verify against the reference.

    Exercises two hold settings (N=2 and N=4) to confirm the held-output streaming
    works end-to-end across the hold range, not just the unit-level front-end.
    """
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    key = bytes(range(32))
    nonce = bytes(range(12))
    counter = 1
    exp = chacha20_ref.chacha20_block(key, counter, nonce)

    for hold in (1, 3):                       # N = 2 and N = 4
        await reset(dut, hold=hold)
        await load_config(dut, key, counter, nonce, hold=hold)
        await send_frame(dut, CMD_GEN, bytes([1]), hold=hold)
        got = await read_bytes(dut, 64)
        assert got == exp, (
            f"parallel GEN (hold={hold}) mismatch:\n  got={got.hex()}\n  exp={exp.hex()}"
        )
        await wait_busy_low(dut)              # BUSY should drop when streaming completes


@cocotb.test()
async def parallel_crypt_roundtrip(dut):
    """Encrypt a message over the parallel bus, then decrypt it back.

    Exercises the bidirectional CRYPT interleave (plaintext in / ciphertext out)
    over the parallel front-end, a path GEN does not cover.
    """
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    key = bytes((i ^ 0x33) & 0xFF for i in range(32))
    nonce = bytes((i + 1) & 0xFF for i in range(12))
    counter = 0x40
    random.seed(0x5151)
    plaintext = bytes(random.randrange(256) for _ in range(24))   # < 64 -> single block
    L = len(plaintext)

    async def crypt(data: bytes) -> bytes:
        await reset(dut)
        await load_config(dut, key, counter, nonce)
        # CRYPT command + 2-byte little-endian length
        await send_byte(dut, CMD_CRYPT)
        await send_byte(dut, L & 0xFF)
        await send_byte(dut, (L >> 8) & 0xFF)
        # Wait for the core to compute the first keystream block before feeding
        # plaintext: the controller ignores RX while it is computing (RUN_CRYPT).
        await ClockCycles(dut.clk, CORE_WAIT)
        out = []
        for b in data:
            await send_byte(dut, b)           # plaintext byte
            out.append(await read_one(dut))   # ciphertext byte
        return bytes(out)

    ct = await crypt(plaintext)
    exp_ct = chacha20_ref.chacha20_crypt(key, counter, nonce, plaintext)
    assert ct == exp_ct, (
        f"parallel encrypt mismatch:\n  got={ct.hex()}\n  exp={exp_ct.hex()}"
    )

    pt = await crypt(ct)                       # decrypt = same op on the ciphertext
    assert pt == plaintext, (
        f"parallel decrypt round-trip failed:\n  pt ={plaintext.hex()}\n  got={pt.hex()}"
    )


def test_full_chip_parallel():
    """pytest entry point: build the full chip and run the parallel cocotb tests."""
    from cocotb_tools.runner import get_runner

    sim = os.getenv("SIM", "icarus")
    test_dir = Path(__file__).resolve().parent
    src = test_dir.parent.parent / "src"
    build_dir = test_dir.parent / "sim_build" / "full_chip_parallel"

    runner = get_runner(sim)
    runner.build(
        sources=[
            src / "tt_um_egurapha_chacha20.sv",
            src / "chacha20_controller.sv",
            src / "chacha20_core.sv",
            src / "quarter_round.sv",
            src / "adder32.sv",
            src / "uart_rx.sv",
            src / "uart_tx.sv",
            src / "parallel_io.sv",
        ],
        hdl_toplevel="tt_um_egurapha_chacha20",
        build_dir=build_dir,
        timescale=("1ns", "1ps"),
        always=True,
    )
    runner.test(
        hdl_toplevel="tt_um_egurapha_chacha20",
        test_module="test_full_chip_parallel",
        test_dir=test_dir,
        build_dir=build_dir,
        results_xml=str(build_dir / "results.xml"),
        timescale=("1ns", "1ps"),
    )
