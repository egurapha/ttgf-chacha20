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
    collector(dut, received)
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
