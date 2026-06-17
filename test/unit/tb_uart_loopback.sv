/*
 * Copyright (c) 2026 Raphael Eguchi
 * SPDX-License-Identifier: Apache-2.0
 *
 * Loopback harness for the UART pair.
 *
 * Connects uart_tx's serial output directly to uart_rx's serial input (the
 * `line` net), so a byte driven into the transmitter should reappear, intact,
 * out of the receiver. Both share the same BAUD_DIV. The cocotb test drives the
 * tx-side handshake (data/send/busy) and observes the rx-side (data/valid).
 */

`default_nettype none

module tb_uart_loopback #(
    parameter int BAUD_DIV = 8
) (
    input  logic       clk,
    input  logic       rst_n,
    // Transmitter side (driven by cocotb).
    input  logic [7:0] tx_data,
    input  logic       tx_send,
    output logic       tx_busy,
    // Receiver side (observed by cocotb).
    output logic [7:0] rx_data,
    output logic       rx_valid
);
    logic line;  // the serial wire: tx.tx -> rx.rx

    uart_tx #(.BAUD_DIV(BAUD_DIV)) u_tx (
        .clk  (clk),
        .rst_n(rst_n),
        .data (tx_data),
        .send (tx_send),
        .busy (tx_busy),
        .tx   (line)
    );

    uart_rx #(.BAUD_DIV(BAUD_DIV)) u_rx (
        .clk  (clk),
        .rst_n(rst_n),
        .rx   (line),
        .data (rx_data),
        .valid(rx_valid)
    );
endmodule
