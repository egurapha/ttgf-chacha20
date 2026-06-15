# SPDX-FileCopyrightText: © 2026 Raphael Eguchi
# SPDX-License-Identifier: Apache-2.0
"""Unit test for the `chacha20_core` module.

Two checks:
  * RFC 8439 section 2.3.2 keystream block (independent reference value).
  * Random cross-check against the Python reference (chacha20_ref.chacha20_block).

`chacha20_core` is sequential: it instantiates four `quarter_round` units and
runs 20 round-cycles per block, so the test drives a clock, resets, pulses
`start`, waits for `done`, then reads `block`.

Bus packing (SPEC section 1.1): word `i` sits at bit `32*i`, little-endian — so a
32-byte key maps to the 256-bit bus as `int.from_bytes(key, "little")`, and the
512-bit `block` output decodes back the same way.

`chacha20_ref` is made importable by test/conftest.py.

Run from the test/ directory:
    ./run_unit_tests.sh -k chacha20_core
"""

import os
import random
import struct
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer, with_timeout

import chacha20_ref


async def run_block(dut, key: bytes, counter: int, nonce: bytes) -> int:
    """Load inputs, pulse start, wait for done, return the 512-bit block as int."""
    # Drive the configuration buses (little-endian word packing, see module docstring).
    dut.key.value = int.from_bytes(key, "little")
    dut.nonce.value = int.from_bytes(nonce, "little")
    dut.counter.value = counter

    # One-cycle start pulse.
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0

    # Wait for the block to complete. `done` is held high from the previous block
    # until the next `start`, but a *rising* edge only fires on a genuine 0->1
    # transition — so the stale high is ignored: after `start` the core drops `done`
    # (in INIT) and raises it again (in DONE), and we catch exactly that rise.
    # The timeout guards against a hung FSM (latency is ~22 cycles).
    await with_timeout(RisingEdge(dut.done), 1, "us")

    # The core now exposes one 32-bit word at a time (block_word) selected by
    # word_idx, instead of a 512-bit block bus. Read all 16 words and reassemble
    # the same little-endian-packed 512-bit value (word i at bits [32*i +: 32]).
    block_int = 0
    for w in range(16):
        dut.word_idx.value = w
        await Timer(1, unit="ns")  # block_word is combinational on word_idx
        block_int |= int(dut.block_word.value) << (32 * w)
    return block_int


async def reset(dut):
    """Hold reset low for a few cycles, then release."""
    dut.start.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


# Published known-answer vectors: the five block-function tests from RFC 8439
# Appendix A.1, plus the worked example from section 2.3.2. Values are copied in
# the RFC's colon-separated byte notation so they cross-reference directly against
# the document. Each is (name, key, counter, nonce, keystream). These anchor the
# DUT to the spec itself (the random test below only proves DUT == our reference).
RFC_VECTORS = [
    (
        "A.1 #1",
        "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:"
        "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00",
        0,
        "00:00:00:00:00:00:00:00:00:00:00:00",
        "76:b8:e0:ad:a0:f1:3d:90:40:5d:6a:e5:53:86:bd:28:"
        "bd:d2:19:b8:a0:8d:ed:1a:a8:36:ef:cc:8b:77:0d:c7:"
        "da:41:59:7c:51:57:48:8d:77:24:e0:3f:b8:d8:4a:37:"
        "6a:43:b8:f4:15:18:a1:1c:c3:87:b6:69:b2:ee:65:86",
    ),
    (
        "A.1 #2",
        "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:"
        "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00",
        1,
        "00:00:00:00:00:00:00:00:00:00:00:00",
        "9f:07:e7:be:55:51:38:7a:98:ba:97:7c:73:2d:08:0d:"
        "cb:0f:29:a0:48:e3:65:69:12:c6:53:3e:32:ee:7a:ed:"
        "29:b7:21:76:9c:e6:4e:43:d5:71:33:b0:74:d8:39:d5:"
        "31:ed:1f:28:51:0a:fb:45:ac:e1:0a:1f:4b:79:4d:6f",
    ),
    (
        "A.1 #3",
        "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:"
        "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:01",
        1,
        "00:00:00:00:00:00:00:00:00:00:00:00",
        "3a:eb:52:24:ec:f8:49:92:9b:9d:82:8d:b1:ce:d4:dd:"
        "83:20:25:e8:01:8b:81:60:b8:22:84:f3:c9:49:aa:5a:"
        "8e:ca:00:bb:b4:a7:3b:da:d1:92:b5:c4:2f:73:f2:fd:"
        "4e:27:36:44:c8:b3:61:25:a6:4a:dd:eb:00:6c:13:a0",
    ),
    (
        "A.1 #4",
        "00:ff:00:00:00:00:00:00:00:00:00:00:00:00:00:00:"
        "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00",
        2,
        "00:00:00:00:00:00:00:00:00:00:00:00",
        "72:d5:4d:fb:f1:2e:c4:4b:36:26:92:df:94:13:7f:32:"
        "8f:ea:8d:a7:39:90:26:5e:c1:bb:be:a1:ae:9a:f0:ca:"
        "13:b2:5a:a2:6c:b4:a6:48:cb:9b:9d:1b:e6:5b:2c:09:"
        "24:a6:6c:54:d5:45:ec:1b:73:74:f4:87:2e:99:f0:96",
    ),
    (
        "A.1 #5",
        "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:"
        "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00",
        0,
        "00:00:00:00:00:00:00:00:00:00:00:02",
        "c2:c6:4d:37:8c:d5:36:37:4a:e2:04:b9:ef:93:3f:cd:"
        "1a:8b:22:88:b3:df:a4:96:72:ab:76:5b:54:ee:27:c7:"
        "8a:97:0e:0e:95:5c:14:f3:a8:8e:74:1b:97:c2:86:f7:"
        "5f:8f:c2:99:e8:14:83:62:fa:19:8a:39:53:1b:ed:6d",
    ),
    (
        "2.3.2",
        "00:01:02:03:04:05:06:07:08:09:0a:0b:0c:0d:0e:0f:"
        "10:11:12:13:14:15:16:17:18:19:1a:1b:1c:1d:1e:1f",
        1,
        "00:00:00:09:00:00:00:4a:00:00:00:00",
        "10:f1:e7:e4:d1:3b:59:15:50:0f:dd:1f:a3:20:71:c4:"
        "c7:d1:f4:c7:33:c0:68:03:04:22:aa:9a:c3:d4:6c:4e:"
        "d2:82:64:46:07:9f:aa:09:14:c2:d7:05:d9:8b:02:a2:"
        "b5:12:9c:d1:de:16:4e:b9:cb:d0:83:e8:a2:50:3c:4e",
    ),
]


@cocotb.test()
async def rfc_known_answer_vectors(dut):
    """RFC 8439 published known-answer keystream blocks (Appendix A.1 + 2.3.2)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    for name, key_hex, counter, nonce_hex, ks_hex in RFC_VECTORS:
        key = bytes.fromhex(key_hex.replace(":", ""))
        nonce = bytes.fromhex(nonce_hex.replace(":", ""))
        exp = int.from_bytes(bytes.fromhex(ks_hex.replace(":", "")), "little")

        got = await run_block(dut, key, counter, nonce)
        assert got == exp, (
            f"RFC {name} mismatch:\n"
            f"  got = {got:0128x}\n"
            f"  exp = {exp:0128x}"
        )


@cocotb.test()
async def random_vectors(dut):
    """Cross-check random key/counter/nonce against the reference block function."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    random.seed(0xC0FFEE)
    for _ in range(50):
        key = random.randbytes(32)
        nonce = random.randbytes(12)
        counter = random.getrandbits(32)

        ks = chacha20_ref.chacha20_block(key, counter, nonce)
        exp = int.from_bytes(ks, "little")

        got = await run_block(dut, key, counter, nonce)
        assert got == exp, (
            f"mismatch for key={key.hex()} counter={counter:#x} nonce={nonce.hex()}:\n"
            f"  got = {got:0128x}\n"
            f"  exp = {exp:0128x}"
        )


def test_chacha20_core():
    """pytest entry point: build the module and run the cocotb tests above."""
    from cocotb_tools.runner import get_runner

    sim = os.getenv("SIM", "icarus")
    test_dir = Path(__file__).resolve().parent  # test/unit
    src = test_dir.parent.parent / "src"  # ../../src
    build_dir = test_dir.parent / "sim_build" / "chacha20_core"  # gitignored

    runner = get_runner(sim)
    runner.build(
        sources=[src / "chacha20_core.sv", src / "quarter_round.sv", src / "adder32.sv"],
        hdl_toplevel="chacha20_core",
        build_dir=build_dir,
        timescale=("1ns", "1ps"),
        always=True,
    )
    runner.test(
        hdl_toplevel="chacha20_core",
        test_module="test_chacha20_core",
        test_dir=test_dir,
        build_dir=build_dir,
        results_xml=str(build_dir / "results.xml"),
        timescale=("1ns", "1ps"),
    )
