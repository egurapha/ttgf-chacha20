/*
 * Copyright (c) 2026 Raphael Eguchi
 * SPDX-License-Identifier: Apache-2.0
 *
 * Test harness for the chacha20_controller unit test (SPEC section 7.5).
 *
 * Wires the real `chacha20_controller` to the real `chacha20_core` over the
 * core handshake (start/done/block + key/nonce/counter), and exposes the
 * controller's byte-level host interface (rx_data/rx_valid, tx_data/tx_send/
 * tx_busy) plus the status pins to the cocotb testbench.
 *
 * No UART modules are involved: per SPEC 7.5 the controller is driven at the
 * byte level (rx_data/rx_valid directly) and the tx stream is snooped on
 * tx_data/tx_send. The transmitter is modelled by the test driving tx_busy.
 */

`default_nettype none

module tb_controller_core (
    input  logic       clk,
    input  logic       rst_n,
    // Host byte interface (driven / observed by cocotb).
    input  logic [7:0] rx_data,
    input  logic       rx_valid,
    input  logic       tx_busy,
    output logic [7:0] tx_data,
    output logic       tx_send,
    output logic       busy,
    output logic       err
);
    // controller <-> core nets
    logic [255:0] core_key;
    logic [ 95:0] core_nonce;
    logic [ 31:0] core_counter;
    logic         core_start;
    logic         core_done;
    logic [ 31:0] core_block_word;
    logic [  3:0] core_word_idx;

    chacha20_controller u_ctrl (
        .clk            (clk),
        .rst_n          (rst_n),
        .core_done      (core_done),
        .core_block_word(core_block_word),
        .core_word_idx  (core_word_idx),
        .core_key       (core_key),
        .core_nonce  (core_nonce),
        .core_counter(core_counter),
        .core_start  (core_start),
        .busy        (busy),
        .err         (err),
        .rx_data     (rx_data),
        .rx_valid    (rx_valid),
        .tx_busy     (tx_busy),
        .tx_data     (tx_data),
        .tx_send     (tx_send)
    );

    chacha20_core u_core (
        .clk    (clk),
        .rst_n  (rst_n),
        .key    (core_key),
        .nonce  (core_nonce),
        .counter(core_counter),
        .start    (core_start),
        .done     (core_done),
        .word_idx (core_word_idx),
        .block_word(core_block_word)
    );
endmodule
