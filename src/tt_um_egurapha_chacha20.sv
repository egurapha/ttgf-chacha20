/*
 * Copyright (c) 2026 Raphael Eguchi
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_egurapha_chacha20 #(
    parameter int BAUD_DIV = 434
) (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);
    // Registers.
    logic [7:0] rx_data, tx_data;
    logic rx_valid, tx_send, tx_busy, busy, err, tx_line;
    logic [255:0] core_key;
    logic [ 95:0] core_nonce;
    logic [ 31:0] core_counter;
    logic core_start, core_done;
    logic [511:0] core_block;
    logic _unused;

    // Routing.
    assign uo_out  = {3'b0, tx_line, 2'b0, err, busy};
    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0;
    assign _unused = &{ena, ui_in[7:4], ui_in[2:0], uio_in, 1'b0};

    // Modules.
    uart_rx #(
        .BAUD_DIV(BAUD_DIV)
    ) u_rx (
        .clk(clk),
        .rst_n(rst_n),
        .rx(ui_in[3]),
        .data(rx_data),
        .valid(rx_valid)
    );

    uart_tx #(
        .BAUD_DIV(BAUD_DIV)
    ) u_tx (
        .clk(clk),
        .rst_n(rst_n),
        .data(tx_data),
        .send(tx_send),
        .busy(tx_busy),
        .tx(tx_line)
    );

    chacha20_core u_core (
        .clk(clk),
        .rst_n(rst_n),
        .key(core_key),
        .nonce(core_nonce),
        .counter(core_counter),
        .start(core_start),
        .done(core_done),
        .block(core_block)
    );

    chacha20_controller u_ctrl (
        .clk(clk),
        .rst_n(rst_n),
        .rx_data(rx_data),
        .rx_valid(rx_valid),
        .tx_data(tx_data),
        .tx_send(tx_send),
        .tx_busy(tx_busy),
        .core_key(core_key),
        .core_nonce(core_nonce),
        .core_counter(core_counter),
        .core_start(core_start),
        .core_done(core_done),
        .core_block(core_block),
        .busy(busy),
        .err(err)
    );

endmodule
