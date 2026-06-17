![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# ChaCha20 stream cipher (Tiny Tapeout)

A hardware implementation of the ChaCha20 stream cipher (RFC 8439), built for Tiny Tapeout on the GF180MCU process.

## About ChaCha20

ChaCha20 is a modern stream cipher (Daniel J. Bernstein's refinement of Salsa20), standardized in [RFC 8439](https://www.rfc-editor.org/rfc/rfc8439) and widely used in TLS, SSH, and WireGuard. It is an Add-Rotate-XOR (ARX) design: no S-boxes or lookup tables, just additions, bit rotations, and XORs, which makes it compact and fast in hardware. From a 256-bit key, a 96-bit nonce, and a 32-bit block counter it produces a pseudorandom keystream. You encrypt by XORing data with that keystream, and because XOR is self-inverse, decryption is the exact same operation.

## What this chip does

The chip runs the ChaCha20 block function on-chip and exposes two operations:

- **GEN:** stream out the raw keystream.
- **CRYPT:** XOR a stream of data with the keystream (encrypt, or decrypt by feeding the ciphertext back in with the same key, nonce, and counter).

You load the key, nonce, and counter and issue commands from a host over either an 8N1 UART or a faster synchronous parallel byte bus, chosen at runtime by the MODE pin.

The **[datasheet](docs/info.md)** is the place to start if you want to talk to the chip: it has the command protocol, the pin map, and worked examples.

| PDK | Shuttle | Tiles | Clock |
| --- | --- | --- | --- |
| gf180mcuD (GF180MCU) | TTGF26b | 3x4 | 35 MHz |

## Repository

The Verilog sources are in [`src/`](src) (a ChaCha20 block engine, a command FSM, and the UART and parallel front-ends); the datasheet is in [`docs/`](docs); and the cocotb testbenches are in [`test/`](test). To run the test suite (Icarus Verilog and cocotb, both from the OSS CAD Suite):

```sh
cd test
./run_unit_tests.sh
```

## Tiny Tapeout

Tiny Tapeout makes it easier and cheaper to get digital and analog designs manufactured on a real chip. Learn more at [tinytapeout.com](https://tinytapeout.com).

- [Project datasheet](docs/info.md)
- [FAQ](https://tinytapeout.com/faq/)
- [Submit your design](https://app.tinytapeout.com/)
