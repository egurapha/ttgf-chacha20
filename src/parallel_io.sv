/*
 * Copyright (c) 2026 Raphael Eguchi
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Parallel byte front-end: a synchronous alternative to the UART. Presents the
// same byte interface to chacha20_controller as uart_rx/uart_tx (rx_data/rx_valid
// in, tx_data/tx_send/tx_busy out), but moves a whole byte per clock instead of
// serializing 10 bit-times.
//
// Input  (host -> chip): the host drives `pdata_in` and pulses `wr` for one
//   cycle; the byte is captured on that clock edge (rx_valid pulses with it).
//   No baud, oversampling, or framing: the shared clock and strobe define validity.
//
// Output (chip -> host): on `tx_send` the byte is driven on `pdata_out` and
//   `valid` is held high for (hold_sel + 1) clock cycles. The hold gives the
//   latency-bound host reader (RP2040 PIO needs a cycle to see `valid` and
//   another to read) plus the slew-limited output pad a wide, stable sampling
//   window. `hold_sel` comes from pins, so the hold is tunable at runtime to
//   match the output pad's slew behavior.
//
// The handshake design (held output for a latency-bound PIO reader, runtime
// hold, bubble tolerance, contiguous data pins) follows the parallel/PIO
// interface of the BLAKE2s Tiny Tapeout project by Essenceia:
//   https://github.com/Essenceia/blake2_asic
module parallel_io (
    input  logic       clk,
    input  logic       rst_n,
    // Parallel pins (host side)
    input  logic [7:0] pdata_in,   // data bus in   (ui_in[7:0])
    input  logic       wr,         // write strobe  (uio[0])
    input  logic [1:0] hold_sel,   // output hold = hold_sel + 1 cycles (uio[5:4])
    output logic [7:0] pdata_out,  // data bus out  (uo_out[7:0])
    output logic       valid,      // output valid  (uio[1])
    // Controller byte interface (identical to the UART side)
    output logic [7:0] rx_data,
    output logic       rx_valid,
    input  logic [7:0] tx_data,
    input  logic       tx_send,
    output logic       tx_busy
);
    // ---- Input: capture a byte on the wr strobe. ----
    // rx_valid pulses for one cycle aligned with the captured byte, matching
    // uart_rx's valid/data contract to the controller.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rx_valid <= 1'b0;
            rx_data  <= '0;
        end else begin
            rx_valid <= wr;
            if (wr) rx_data <= pdata_in;
        end
    end

    // ---- Output: drive a byte and hold valid for (hold_n + 1) cycles. ----
    typedef enum logic {P_IDLE, P_SEND} tx_state_t;
    tx_state_t   state;
    logic [7:0]  out_byte;
    logic [1:0]  cnt;
    logic [1:0]  hold_n;   // latched at send time so a mid-byte pin change is harmless

    assign valid     = (state == P_SEND);
    assign tx_busy   = (state == P_SEND);  // controller stalls while the byte is held
    assign pdata_out = out_byte;           // holds last byte; ignored when !valid

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state    <= P_IDLE;
            out_byte <= '0;
            cnt      <= '0;
            hold_n   <= '0;
        end else begin
            case (state)
                P_IDLE: begin
                    if (tx_send) begin
                        out_byte <= tx_data;
                        cnt      <= '0;
                        hold_n   <= hold_sel;
                        state    <= P_SEND;
                    end
                end
                P_SEND: begin
                    if (cnt == hold_n) state <= P_IDLE;  // held (hold_n + 1) cycles
                    else cnt <= cnt + 2'd1;
                end
                default: state <= P_IDLE;
            endcase
        end
    end
endmodule
