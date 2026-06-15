/*
 * Copyright (c) 2026 Raphael Eguchi
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module uart_rx #(
    parameter int BAUD_DIV = 434  // cycles per bit.
) (
    // Input.
    input logic clk,
    input logic rst_n,
    input logic rx,
    // Output.
    output logic [7:0] data,
    output logic valid
);
    // Registers.
    logic [1:0] rx_sync;  // to prevent metastability.
    logic [$clog2(BAUD_DIV):0] baud_cnt;
    logic [2:0] bit_cnt;
    logic [7:0] shift;
    logic tick;
    logic half_tick;

    // FSM.
    typedef enum logic [2:0] {
        IDLE,
        START,
        DATA,
        STOP
    } state_t;
    state_t fsm;

    // Main.
    assign tick = (baud_cnt == ($clog2(BAUD_DIV) + 1)'(BAUD_DIV - 1));  // high at end of bit cycle.
    assign half_tick = (baud_cnt == ($clog2(BAUD_DIV) + 1)'(BAUD_DIV / 2 - 1));
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rx_sync <= 2'b11;
            valid <= 1'b0;
            fsm <= IDLE;
            baud_cnt <= '0;
            bit_cnt  <= '0;
            shift    <= '0;
        end else begin
            rx_sync <= {rx_sync[0], rx};  // shift the rx signal.
            valid   <= 1'b0;
            if (fsm == IDLE || (fsm == START && half_tick)  // half-bit phase shift.
                || ((fsm == DATA || fsm == STOP) && tick)) begin
                baud_cnt <= '0;
            end else begin
                baud_cnt <= baud_cnt + 1'b1;
            end
            case (fsm)
                IDLE: begin
                    if (rx_sync[1] == 1'b0) begin
                        fsm <= START;
                    end
                end
                START: begin
                    if (half_tick) begin
                        if (rx_sync[1] == 1'b0) begin
                            // detect sync'ed start.
                            bit_cnt <= 3'd0;
                            fsm <= DATA;
                        end else begin
                            fsm <= IDLE;
                        end
                    end
                end
                DATA: begin
                    if (tick) begin  // note, half-phase shifted already here.
                        // latch bits into the shift storage.
                        shift[bit_cnt] <= rx_sync[1];
                        if (bit_cnt == 3'd7) begin
                            // byte complete.
                            fsm <= STOP;
                        end else begin
                            bit_cnt <= bit_cnt + 1'b1;
                        end
                    end
                end
                STOP: begin
                    if (tick) begin
                        data  <= shift;
                        valid <= 1'b1;
                        fsm   <= IDLE;
                    end
                end
                default: fsm <= IDLE;
            endcase
        end
    end
endmodule
