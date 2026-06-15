# SPDX-FileCopyrightText: © 2026 Raphael Eguchi
# SPDX-License-Identifier: Apache-2.0
"""Unit test for the `chacha20_controller` module — GEN path (SPEC section 7.5).

Drives the controller at the byte level (rx_data/rx_valid directly, no serial
timing) through the `tb_controller_core` wrapper, which wires the controller to
the real `chacha20_core`. The streamed `tx` bytes are snooped on tx_send/tx_data
and compared against the golden reference `chacha20_ref.chacha20_block()`.

Covered here (GEN only; CRYPT is added later):
  * Single-block GEN (N=1): the 64 streamed bytes equal one keystream block.
  * Multi-block GEN (N>1): 64*N bytes, with the counter incrementing per block.
  * Randomised key/nonce/counter cross-check against the reference.
  * GEN N=0: legal no-op, produces no output.

The transmitter is modelled by tying `tx_busy` low (always ready); the
controller's `!tx_busy && !tx_send` guard still paces output to one byte every
two cycles, and the collector records each byte on the tx_send pulse.

Run from the test/ directory:
    ./run_unit_tests.sh -k chacha20_controller
"""

import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

import chacha20_ref

# Command bytes (SPEC section 4).
CMD_LOAD_KEY = 0x01
CMD_LOAD_NONCE = 0x02
CMD_LOAD_CTR = 0x03
CMD_GEN = 0x04
CMD_CRYPT = 0x05


async def reset(dut):
    """Hold reset low a few cycles; inputs de-asserted. tx_busy tied low."""
    dut.rx_data.value = 0
    dut.rx_valid.value = 0
    dut.tx_busy.value = 0  # transmitter modelled as always ready
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def send_byte(dut, value: int):
    """Present one byte with a one-cycle rx_valid strobe, then an idle cycle."""
    dut.rx_data.value = value
    dut.rx_valid.value = 1
    await RisingEdge(dut.clk)  # controller samples the byte on this edge
    dut.rx_valid.value = 0
    await RisingEdge(dut.clk)  # idle gap (covers state-transition latency)


async def send_frame(dut, cmd: int, payload: bytes):
    """Send a command byte + payload, then wait for the controller to go idle.

    Used for the LOAD commands, which produce no output: once `busy` falls the
    controller is back in IDLE and ready for the next frame.
    """
    await send_byte(dut, cmd)
    for b in payload:
        await send_byte(dut, b)
    while dut.busy.value == 1:  # wait for APPLY -> IDLE
        await RisingEdge(dut.clk)


async def send_data_byte(dut, value: int, gap: int = 130):
    """Feed one CRYPT data byte, then idle for `gap` cycles.

    The controller has no input buffer (SPEC 5.3): it relies on UART being far
    slower than a block computation, so a new data byte never arrives while it
    is re-blocking (~22 cycles). The gap models that spacing — comfortably
    longer than a reblock — so bytes are consumed one at a time, in order.
    """
    dut.rx_data.value = value
    dut.rx_valid.value = 1
    await RisingEdge(dut.clk)
    dut.rx_valid.value = 0
    await ClockCycles(dut.clk, gap)


def collector(dut, sink: list):
    """Background coroutine: record tx_data on every tx_send pulse."""

    async def _run():
        while True:
            await RisingEdge(dut.clk)
            if dut.tx_send.value == 1:
                sink.append(int(dut.tx_data.value))

    return cocotb.start_soon(_run())


def expected_keystream(key: bytes, counter: int, nonce: bytes, n: int) -> bytes:
    """Reference: N consecutive keystream blocks, counter incrementing per block."""
    return b"".join(
        chacha20_ref.chacha20_block(key, counter + i, nonce) for i in range(n)
    )


async def load_config(dut, key: bytes, counter: int, nonce: bytes):
    """Issue LOAD_KEY / LOAD_NONCE / LOAD_CTR with little-endian byte packing."""
    await send_frame(dut, CMD_LOAD_KEY, key)
    await send_frame(dut, CMD_LOAD_NONCE, nonce)
    await send_frame(dut, CMD_LOAD_CTR, counter.to_bytes(4, "little"))


async def run_gen(dut, key, counter, nonce, n, timeout_cycles=20000):
    """Load config, issue GEN N, collect the streamed bytes, return them."""
    received = []
    task = collector(dut, received)
    await load_config(dut, key, counter, nonce)

    await send_byte(dut, CMD_GEN)
    await send_byte(dut, n)

    want = 64 * n
    waited = 0
    while len(received) < want and waited < timeout_cycles:
        await RisingEdge(dut.clk)
        waited += 1
    # Settle a few cycles to catch any spurious extra bytes.
    await ClockCycles(dut.clk, 20)
    task.kill()
    return bytes(received)


async def run_crypt(dut, key, counter, nonce, data: bytes, timeout_cycles=60000):
    """Load config, issue CRYPT (L + data), collect the streamed bytes.

    Sends the 2-byte little-endian length, waits for the first keystream block
    to compute, then feeds each data byte spaced out (see send_data_byte).
    Returns the L crypted bytes.
    """
    received = []
    task = collector(dut, received)
    await load_config(dut, key, counter, nonce)

    L = len(data)
    await send_byte(dut, CMD_CRYPT)
    await send_byte(dut, L & 0xFF)  # length low byte (LE)
    await send_byte(dut, (L >> 8) & 0xFF)  # length high byte

    await ClockCycles(dut.clk, 130)  # let the first block compute (pipelined core ~84 cyc)
    for b in data:
        await send_data_byte(dut, b)

    waited = 0
    while len(received) < L and waited < timeout_cycles:
        await RisingEdge(dut.clk)
        waited += 1
    await ClockCycles(dut.clk, 20)
    task.kill()
    return bytes(received)


@cocotb.test()
async def gen_single_block(dut):
    """GEN N=1: 64 streamed bytes equal one reference keystream block."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    key = bytes(range(32))
    nonce = bytes(range(12))
    counter = 1

    got = await run_gen(dut, key, counter, nonce, 1)
    exp = expected_keystream(key, counter, nonce, 1)
    assert got == exp, f"GEN N=1 mismatch:\n  got={got.hex()}\n  exp={exp.hex()}"


@cocotb.test()
async def gen_multi_block(dut):
    """GEN N=3: 192 bytes, counter increments per 64-byte block."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    key = bytes((i * 7) & 0xFF for i in range(32))
    nonce = bytes((i * 5 + 1) & 0xFF for i in range(12))
    counter = 0xFFFFFFFE  # also exercises counter wrap across blocks

    got = await run_gen(dut, key, counter, nonce, 3)
    exp = expected_keystream(key, counter, nonce, 3)
    assert got == exp, f"GEN N=3 mismatch:\n  got={got.hex()}\n  exp={exp.hex()}"


@cocotb.test()
async def gen_random_vectors(dut):
    """Random key/nonce/counter cross-checked against the reference."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    random.seed(0xC04401)
    for _ in range(8):
        key = random.randbytes(32)
        nonce = random.randbytes(12)
        counter = random.getrandbits(32)
        n = random.randint(1, 3)

        got = await run_gen(dut, key, counter, nonce, n)
        exp = expected_keystream(key, counter, nonce, n)
        assert got == exp, (
            f"random GEN mismatch (n={n}, ctr={counter:#x}):\n"
            f"  got={got.hex()}\n  exp={exp.hex()}"
        )


@cocotb.test()
async def gen_zero_is_noop(dut):
    """GEN N=0: legal no-op, no bytes streamed."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    key = bytes(range(32))
    nonce = bytes(range(12))
    got = await run_gen(dut, key, 0, nonce, 0, timeout_cycles=400)
    assert got == b"", f"GEN N=0 should emit nothing, got {got.hex()}"
    assert dut.busy.value == 0, "controller should be idle after a no-op GEN"


@cocotb.test()
async def crypt_single_block(dut):
    """CRYPT L<64 (single block): output equals chacha20_crypt() of the input."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    key = bytes(range(32))
    nonce = bytes(range(12))
    counter = 7
    data = bytes((i * 3 + 1) & 0xFF for i in range(40))  # 40 < 64

    got = await run_crypt(dut, key, counter, nonce, data)
    exp = chacha20_ref.chacha20_crypt(key, counter, nonce, data)
    assert got == exp, f"CRYPT L=40 mismatch:\n  got={got.hex()}\n  exp={exp.hex()}"


@cocotb.test()
async def crypt_multi_block(dut):
    """CRYPT L>64 (spans blocks): counter rolls at the 64-byte boundary."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    key = bytes((i * 11) & 0xFF for i in range(32))
    nonce = bytes((i + 3) & 0xFF for i in range(12))
    counter = 0x1000
    data = bytes((i * 7 + 5) & 0xFF for i in range(130))  # 130 -> 3 blocks

    got = await run_crypt(dut, key, counter, nonce, data)
    exp = chacha20_ref.chacha20_crypt(key, counter, nonce, data)
    assert got == exp, f"CRYPT L=130 mismatch:\n  got={got.hex()}\n  exp={exp.hex()}"


@cocotb.test()
async def crypt_nonaligned_length(dut):
    """CRYPT with L not a multiple of 64 (=100): exactly L bytes, partial block ok."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    key = bytes((i * 5 + 9) & 0xFF for i in range(32))
    nonce = bytes((i * 2) & 0xFF for i in range(12))
    counter = 0xABCD
    data = bytes((i * 13) & 0xFF for i in range(100))

    got = await run_crypt(dut, key, counter, nonce, data)
    exp = chacha20_ref.chacha20_crypt(key, counter, nonce, data)
    assert len(got) == 100, f"expected exactly 100 bytes, got {len(got)}"
    assert got == exp, f"CRYPT L=100 mismatch:\n  got={got.hex()}\n  exp={exp.hex()}"


@cocotb.test()
async def crypt_decrypt_roundtrip(dut):
    """CRYPT a message, feed the ciphertext back through CRYPT -> original plaintext.

    Each run reloads the counter (run_crypt issues LOAD_CTR), so the second pass
    uses the same key/nonce/counter and recovers the plaintext.
    """
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    key = bytes((i ^ 0x5A) & 0xFF for i in range(32))
    nonce = bytes((i ^ 0x3C) & 0xFF for i in range(12))
    counter = 0x2222
    plaintext = bytes((i * 17 + 4) & 0xFF for i in range(80))  # spans 2 blocks

    ciphertext = await run_crypt(dut, key, counter, nonce, plaintext)
    exp_ct = chacha20_ref.chacha20_crypt(key, counter, nonce, plaintext)
    assert ciphertext == exp_ct, "encrypt pass mismatch vs reference"

    recovered = await run_crypt(dut, key, counter, nonce, ciphertext)
    assert recovered == plaintext, (
        f"decrypt round-trip failed:\n  pt ={plaintext.hex()}\n  got={recovered.hex()}"
    )


@cocotb.test()
async def error_on_unknown_command(dut):
    """An unknown command byte asserts `err` and returns to IDLE."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)
    assert dut.err.value == 0, "err should be low after reset"

    await send_byte(dut, 0xFF)  # not a valid command
    await ClockCycles(dut.clk, 4)
    assert dut.err.value == 1, "unknown command should assert err"
    assert dut.busy.value == 0, "controller should be back in IDLE"


@cocotb.test()
async def backpressure_stalls_without_drops(dut):
    """Holding tx_busy high stalls streaming; releasing it streams every byte."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    key = bytes(range(32))
    nonce = bytes(range(12))
    counter = 3

    received = []
    task = collector(dut, received)
    await load_config(dut, key, counter, nonce)

    dut.tx_busy.value = 1  # transmitter jammed busy
    await send_byte(dut, CMD_GEN)
    await send_byte(dut, 1)

    # Core computes the block and enters STREAM_GEN, but nothing can be sent.
    await ClockCycles(dut.clk, 300)
    assert len(received) == 0, f"bytes streamed while tx_busy held high: {len(received)}"

    dut.tx_busy.value = 0  # release backpressure
    waited = 0
    while len(received) < 64 and waited < 20000:
        await RisingEdge(dut.clk)
        waited += 1
    await ClockCycles(dut.clk, 20)
    task.kill()

    exp = chacha20_ref.chacha20_block(key, counter, nonce)
    assert bytes(received) == exp, (
        f"backpressure dropped/corrupted bytes:\n"
        f"  got={bytes(received).hex()}\n  exp={exp.hex()}"
    )


def test_chacha20_controller():
    """pytest entry point: build the harness and run the cocotb tests."""
    from cocotb_tools.runner import get_runner

    sim = os.getenv("SIM", "icarus")
    test_dir = Path(__file__).resolve().parent  # test/unit
    src = test_dir.parent.parent / "src"  # ../../src
    build_dir = test_dir.parent / "sim_build" / "chacha20_controller"

    runner = get_runner(sim)
    runner.build(
        sources=[
            test_dir / "tb_controller_core.sv",
            src / "chacha20_controller.sv",
            src / "chacha20_core.sv",
            src / "quarter_round.sv",
            src / "adder32.sv",
        ],
        hdl_toplevel="tb_controller_core",
        build_dir=build_dir,
        timescale=("1ns", "1ps"),
        always=True,
    )
    runner.test(
        hdl_toplevel="tb_controller_core",
        test_module="test_chacha20_controller",
        test_dir=test_dir,
        build_dir=build_dir,
        results_xml=str(build_dir / "results.xml"),
        timescale=("1ns", "1ps"),
    )
