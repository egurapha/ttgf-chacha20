# SPDX-FileCopyrightText: © 2026 Raphael Eguchi
# SPDX-License-Identifier: Apache-2.0
"""Multi-block operations over the PARALLEL interface (spanning 64-byte blocks).

test_full_chip_parallel.py only covers single-block cases (GEN N=1, CRYPT L<64).
This file exercises the cross-block path on the real top-level + parallel
front-end: the counter increment at each 64-byte boundary and the front-end
resuming after the inter-block core recompute (RUN_GEN / RUN_CRYPT).

CRYPT is the interesting case. The controller originally assumed the host link
was always slower than a block recompute (~84 cycles), so it did not buffer a
byte that arrived while the core was re-blocking. That held for the UART
(2000 cycles/byte at BAUD_DIV=200) but not for the fast parallel bus: a host that
paced only by the output handshake drove the next plaintext byte into the
recompute window at each 64-byte boundary, where it was dropped and the stream
stalled. The controller now latches such a byte into its pending/d_in holding
register during RUN_CRYPT, so a fast parallel host streaming across block
boundaries works with no boundary pacing. These tests are the regression for that
fix: they send a plaintext byte and immediately read the ciphertext byte, with NO
extra delay at the boundaries.

Run from the test/ directory:
    ./run_unit_tests.sh -k parallel_multiblock
"""

import os
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

MODE_BIT = 3       # uio[3] = 1 -> parallel interface
WR_BIT = 0         # uio[0]  = write strobe
VALID_BIT = 1      # uio_out[1] = output valid
BUSY_BIT = 2       # uio_out[2] = controller busy
HOLD_SEL = 1       # uio[5:4]; output held HOLD_SEL+1 = 2 cycles
GAP = 2            # idle cycles between input bytes within a frame
CORE_WAIT = 120    # cycles for the FIRST block to compute (pipelined core ~84 cyc)

KEY = bytes((i ^ 0x33) & 0xFF for i in range(32))
NONCE = bytes((i + 1) & 0xFF for i in range(12))
COUNTER = 0x40


def _uio(wr, hold=HOLD_SEL):
    return (1 << MODE_BIT) | ((hold & 0x3) << 4) | (wr << WR_BIT)


async def reset(dut, hold=HOLD_SEL):
    dut.ui_in.value = 0
    dut.uio_in.value = _uio(wr=0, hold=hold)
    dut.ena.value = 1
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


def _busy(dut):
    return (int(dut.uio_out.value) >> BUSY_BIT) & 1


async def wait_busy_low(dut, timeout=20_000):
    w = 0
    while w < timeout:
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        if _busy(dut) == 0:
            return
        w += 1
    raise TimeoutError("BUSY stuck high")


async def send_byte(dut, value, hold=HOLD_SEL):
    dut.ui_in.value = value
    dut.uio_in.value = _uio(wr=1, hold=hold)
    await RisingEdge(dut.clk)
    dut.uio_in.value = _uio(wr=0, hold=hold)
    dut.ui_in.value = 0
    await ClockCycles(dut.clk, GAP)


async def send_frame(dut, cmd, payload, hold=HOLD_SEL):
    await send_byte(dut, cmd, hold)
    for b in payload:
        await send_byte(dut, b, hold)


async def read_one(dut, timeout=5_000):
    """Wait for VALID's rising edge and return the output byte (TimeoutError if none)."""
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


async def read_bytes(dut, n, timeout=400_000):
    """Stream-read n output bytes, one per VALID rising edge (reactive host)."""
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


async def load_config(dut, key, counter, nonce):
    await send_frame(dut, CMD_LOAD_KEY, key)
    await wait_busy_low(dut)
    await send_frame(dut, CMD_LOAD_NONCE, nonce)
    await wait_busy_low(dut)
    await send_frame(dut, CMD_LOAD_CTR, counter.to_bytes(4, "little"))
    await wait_busy_low(dut)


@cocotb.test()
async def parallel_gen_multiblock(dut):
    """GEN N=2 over the parallel bus: 128 bytes = blocks ctr and ctr+1.

    Output-only, so the host just reads VALID rising edges. Verifies the counter
    increments across the boundary and the front-end resumes after the recompute.
    """
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)
    await load_config(dut, KEY, COUNTER, NONCE)
    await send_frame(dut, CMD_GEN, bytes([2]))
    got = await read_bytes(dut, 128)
    exp = (chacha20_ref.chacha20_block(KEY, COUNTER, NONCE)
           + chacha20_ref.chacha20_block(KEY, COUNTER + 1, NONCE))
    assert got == exp, f"parallel GEN N=2 mismatch:\n  got={got.hex()}\n  exp={exp.hex()}"
    await wait_busy_low(dut)


async def crypt_fast(dut, data):
    """CRYPT a message with a fast host: send a plaintext byte, immediately read
    the ciphertext byte, repeat. No pacing at the 64-byte boundaries: this only
    succeeds because the controller holds the boundary byte during RUN_CRYPT.
    """
    await reset(dut)
    await load_config(dut, KEY, COUNTER, NONCE)
    L = len(data)
    await send_byte(dut, CMD_CRYPT)
    await send_byte(dut, L & 0xFF)
    await send_byte(dut, (L >> 8) & 0xFF)
    await ClockCycles(dut.clk, CORE_WAIT)        # let the first block compute
    out = []
    for b in data:
        await send_byte(dut, b)
        out.append(await read_one(dut))
    return bytes(out)


@cocotb.test()
async def parallel_crypt_fast_two_blocks(dut):
    """L=80 CRYPT, fast host, no boundary wait: crosses one block boundary."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    plaintext = bytes((i * 7 + 1) & 0xFF for i in range(80))
    got = await crypt_fast(dut, plaintext)
    exp = chacha20_ref.chacha20_crypt(KEY, COUNTER, NONCE, plaintext)
    assert got == exp, f"fast CRYPT L=80 mismatch:\n  got={got.hex()}\n  exp={exp.hex()}"


@cocotb.test()
async def parallel_crypt_fast_three_blocks(dut):
    """L=200 CRYPT, fast host, no boundary wait: crosses three block boundaries
    (at 64, 128, 192) so consecutive recompute windows are each stressed."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    plaintext = bytes((i * 13 + 7) & 0xFF for i in range(200))
    got = await crypt_fast(dut, plaintext)
    exp = chacha20_ref.chacha20_crypt(KEY, COUNTER, NONCE, plaintext)
    assert got == exp, f"fast CRYPT L=200 mismatch:\n  got={got.hex()}\n  exp={exp.hex()}"


@cocotb.test()
async def parallel_crypt_fast_roundtrip(dut):
    """Encrypt then decrypt a 2-block message with a fast host: recovers plaintext."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    plaintext = bytes((i * 5 + 2) & 0xFF for i in range(130))
    ct = await crypt_fast(dut, plaintext)
    exp_ct = chacha20_ref.chacha20_crypt(KEY, COUNTER, NONCE, plaintext)
    assert ct == exp_ct, f"fast encrypt mismatch:\n  got={ct.hex()}\n  exp={exp_ct.hex()}"
    pt = await crypt_fast(dut, ct)
    assert pt == plaintext, (
        f"fast decrypt round-trip failed:\n  pt ={plaintext.hex()}\n  got={pt.hex()}"
    )


def test_parallel_multiblock():
    """pytest entry point: build the full chip and run the cocotb tests above."""
    from cocotb_tools.runner import get_runner

    sim = os.getenv("SIM", "icarus")
    test_dir = Path(__file__).resolve().parent
    src = test_dir.parent.parent / "src"
    build_dir = test_dir.parent / "sim_build" / "parallel_multiblock"

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
        test_module="test_parallel_multiblock",
        test_dir=test_dir,
        build_dir=build_dir,
        results_xml=str(build_dir / "results.xml"),
        timescale=("1ns", "1ps"),
    )
