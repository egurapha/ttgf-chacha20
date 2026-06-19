#!/usr/bin/env python3
"""Host-side Python interface to the ChaCha20 design on the Tiny Tapeout FPGA
breakout, driven over the chip's UART (single-step, board-independent).

Runs on your PC; under the hood it uses `mpremote` to drive the on-board engine
(chacha20_board.py). The first call programs the bitstream (a few seconds), then
each operation loads key/nonce/counter and runs GEN or CRYPT.

    from chacha20_fpga import ChaCha20FPGA
    c = ChaCha20FPGA().connect()
    ct = c.encrypt(key, nonce, b"hello world")     # 32-byte key, 12-byte nonce
    pt = c.decrypt(key, nonce, ct)                 # == encrypt (XOR keystream)
    ks = c.keystream(key, nonce, 64)

See example.py for a runnable encrypt/decrypt demo.

Port access: the serial port is usually root-owned. Either add yourself to the
`uucp` group (then no sudo), or this falls back to running mpremote under sudo.
"""

import os
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
_BOARD = os.path.join(_HERE, "chacha20_board.py")
_VENV_MP = os.path.expanduser("~/.ttfpga-venv/bin/mpremote")


def _check(key, nonce):
    if len(key) != 32:
        raise ValueError("key must be 32 bytes")
    if len(nonce) != 12:
        raise ValueError("nonce must be 12 bytes")


class ChaCha20FPGA:
    def __init__(self, port="/dev/ttyACM0", mpremote=None, sudo=None):
        self.port = port
        self.mpremote = mpremote or (_VENV_MP if os.path.exists(_VENV_MP) else "mpremote")
        # Use sudo only if the port isn't directly accessible.
        self.sudo = (not os.access(port, os.R_OK | os.W_OK)) if sudo is None else sudo
        self._prepared = False

    # ---- low-level mpremote plumbing ----
    def _cmd(self, *args):
        pre = ["sudo"] if self.sudo else []
        return pre + [self.mpremote, "connect", self.port, *args]

    def _run(self, *args):
        return subprocess.run(self._cmd(*args), capture_output=True, text=True)

    def _exec(self, code):
        r = self._run("exec", code)
        if r.returncode != 0:
            raise RuntimeError("board error:\n" + (r.stderr or "") + (r.stdout or ""))
        return r.stdout

    @staticmethod
    def _hex_result(out):
        for line in reversed(out.strip().splitlines()):
            s = line.strip().lower()
            if s and len(s) % 2 == 0 and all(c in "0123456789abcdef" for c in s):
                return bytes.fromhex(s)
        raise RuntimeError("no hex result from board:\n" + out)

    # ---- lifecycle ----
    def connect(self):
        self._run("fs", "mkdir", ":/lib")  # ignore "already exists"
        cp = self._run("fs", "cp", _BOARD, ":/lib/chacha20_board.py")
        if cp.returncode != 0:
            raise RuntimeError("copying board module failed:\n" + cp.stderr)
        out = self._exec("import chacha20_board as e; print(e.prepare())")
        if "prepared" not in out:
            raise RuntimeError("prepare() did not confirm:\n" + out)
        self._prepared = True
        return self

    def _ensure(self):
        if not self._prepared:
            self.connect()

    # ---- operations ----
    def keystream(self, key, nonce, nbytes, counter=1):
        _check(key, nonce)
        self._ensure()
        out = self._exec(
            "import chacha20_board as e; print(e.gen(bytes.fromhex('%s'),"
            "bytes.fromhex('%s'),%d,%d).hex())"
            % (key.hex(), nonce.hex(), counter, nbytes)
        )
        return self._hex_result(out)

    def encrypt(self, key, nonce, data, counter=1):
        _check(key, nonce)
        self._ensure()
        out = self._exec(
            "import chacha20_board as e; print(e.crypt(bytes.fromhex('%s'),"
            "bytes.fromhex('%s'),%d,bytes.fromhex('%s')).hex())"
            % (key.hex(), nonce.hex(), counter, data.hex())
        )
        return self._hex_result(out)

    decrypt = encrypt  # ChaCha20 is symmetric

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        return False
