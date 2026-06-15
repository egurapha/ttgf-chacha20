/*
 * Copyright (c) 2026 Raphael Eguchi
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module uart_tx #(
    parameter int BAUD_DIV = 434
) (
    // Input.
    input logic clk,
    input logic rst_n,
    input logic [7:0] data,
    input logic send,
    // Output.
    output logic busy,
    output logic tx
);
    // Registers.
    logic [$clog2(BAUD_DIV):0] baud_cnt;
    logic [2:0] bit_cnt;
    logic [7:0] shift;
    logic tick;

    // FSM.
    typedef enum logic [2:0] {
        IDLE,
        START,
        DATA,
        STOP
    } state_t;
    state_t fsm;

    // Main.
    assign busy = (fsm != IDLE);
    assign tick = (baud_cnt == ($clog2(BAUD_DIV) + 1)'(BAUD_DIV - 1));  // high at end of bit cycle.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            tx  <= 1'b1;
            fsm <= IDLE;
            baud_cnt <= '0;
            bit_cnt  <= '0;
            shift    <= '0;
        end else begin
            if (fsm == IDLE || tick) begin
                baud_cnt <= '0;
            end else begin
                baud_cnt <= baud_cnt + 1'b1;
            end
            case (fsm)
                IDLE: begin
                    if (send) begin
                        shift <= data;
                        fsm   <= START;
                    end
                    tx <= 1'b1;
                end
                START: begin
                    tx <= 0;  // start bit.
                    if (tick) begin
                        bit_cnt <= 3'd0;
                        fsm <= DATA;
                    end
                end
                DATA: begin
                    tx <= shift[bit_cnt];
                    if (tick) begin
                        if (bit_cnt == 3'd7) begin
                            fsm <= STOP;
                        end else begin
                            bit_cnt <= bit_cnt + 1'b1;
                        end
                    end
                end
                STOP: begin
                    tx <= 1'b1;  // end bit.
                    if (tick) begin
                        fsm <= IDLE;
                    end
                end
                default: fsm <= IDLE;
            endcase
        end
    end
endmodule
