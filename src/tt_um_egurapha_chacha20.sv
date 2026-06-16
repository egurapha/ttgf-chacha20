/*
 * Copyright (c) 2026 Raphael Eguchi
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Dual-mode front-end: the chip can be driven over the original UART, or over a
// faster parallel byte bus, selected by the MODE pin (uio[3]). Both front-ends
// present the SAME byte interface to chacha20_controller, so the core and
// controller are identical in either mode.
//
//   MODE = 0 (UART):     RX = ui_in[3], TX = uo_out[4], BUSY/ERR = uo_out[0]/[1]
//   MODE = 1 (parallel): data-in = ui_in[7:0], data-out = uo_out[7:0],
//                        WR = uio[0] (in), VALID = uio[1] (out), BUSY = uio[2] (out),
//                        hold_sel = uio[5:4] (in), ERR = uio[6] (out)
module tt_um_egurapha_chacha20 #(
    parameter int BAUD_DIV = 200
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
    // Core wiring.
    logic [255:0] core_key;
    logic [ 95:0] core_nonce;
    logic [ 31:0] core_counter;
    logic         core_start, core_done;
    logic [31:0]  core_block_word;
    logic [3:0]   core_word_idx;
    logic         busy, err;

    // Controller byte interface (muxed between the two front-ends).
    logic [7:0] tx_data;
    logic       tx_send;
    logic [7:0] ctrl_rx_data;
    logic       ctrl_rx_valid, ctrl_tx_busy;

    // UART front-end.
    logic [7:0] u_rx_data;
    logic       u_rx_valid, u_tx_busy, tx_line;

    // Parallel front-end.
    logic [7:0] p_rx_data, p_dout;
    logic       p_rx_valid, p_tx_busy, p_valid;

    logic _unused;

    // ---- Interface select ----
    wire mode      = uio_in[3];
    wire uart_send = tx_send & ~mode;   // send pulse routed only to the active front-end
    wire par_send  = tx_send &  mode;

    assign ctrl_rx_data  = mode ? p_rx_data  : u_rx_data;
    assign ctrl_rx_valid = mode ? p_rx_valid : u_rx_valid;
    assign ctrl_tx_busy  = mode ? p_tx_busy  : u_tx_busy;

    // ---- Pin routing ----
    assign uo_out  = mode ? p_dout : {3'b0, tx_line, 2'b0, err, busy};
    // parallel: uio[1]=VALID, uio[2]=BUSY, uio[6]=ERR are outputs; the rest are inputs.
    assign uio_out = mode ? {1'b0, err, 3'b0, busy, p_valid, 1'b0} : 8'b0;
    assign uio_oe  = mode ? 8'b0100_0110 : 8'b0;
    assign _unused = &{ena, uio_in[7], uio_in[6], uio_in[2], uio_in[1], 1'b0};

    // ---- Front-ends ----
    uart_rx #(
        .BAUD_DIV(BAUD_DIV)
    ) u_rx (
        .clk  (clk),
        .rst_n(rst_n),
        .rx   (ui_in[3]),
        .data (u_rx_data),
        .valid(u_rx_valid)
    );

    uart_tx #(
        .BAUD_DIV(BAUD_DIV)
    ) u_tx (
        .clk  (clk),
        .rst_n(rst_n),
        .data (tx_data),
        .send (uart_send),
        .busy (u_tx_busy),
        .tx   (tx_line)
    );

    parallel_io u_par (
        .clk      (clk),
        .rst_n    (rst_n),
        .pdata_in (ui_in),
        .wr       (uio_in[0]),
        .hold_sel (uio_in[5:4]),
        .pdata_out(p_dout),
        .valid    (p_valid),
        .rx_data  (p_rx_data),
        .rx_valid (p_rx_valid),
        .tx_data  (tx_data),
        .tx_send  (par_send),
        .tx_busy  (p_tx_busy)
    );

    // ---- Core + controller ----
    chacha20_core u_core (
        .clk       (clk),
        .rst_n     (rst_n),
        .key       (core_key),
        .nonce     (core_nonce),
        .counter   (core_counter),
        .start     (core_start),
        .done      (core_done),
        .word_idx  (core_word_idx),
        .block_word(core_block_word)
    );

    chacha20_controller u_ctrl (
        .clk            (clk),
        .rst_n          (rst_n),
        .rx_data        (ctrl_rx_data),
        .rx_valid       (ctrl_rx_valid),
        .tx_data        (tx_data),
        .tx_send        (tx_send),
        .tx_busy        (ctrl_tx_busy),
        .core_key       (core_key),
        .core_nonce     (core_nonce),
        .core_counter   (core_counter),
        .core_start     (core_start),
        .core_done      (core_done),
        .core_word_idx  (core_word_idx),
        .core_block_word(core_block_word),
        .busy           (busy),
        .err            (err)
    );

endmodule
