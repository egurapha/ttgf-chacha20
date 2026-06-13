/*
 * Copyright (c) 2026 Raphael Eguchi
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module chacha20_controller (
    // default.
    input logic clk,
    input logic rst_n,
    // core.
    input logic core_done,
    input logic [511:0] core_block,
    output logic [255:0] core_key,
    output logic [95:0] core_nonce,
    output logic [31:0] core_counter,
    output logic core_start,
    output logic busy,
    output logic err,
    // uart_rx.
    input logic [7:0] rx_data,
    input logic rx_valid,  // high the tick after receiving a byte.
    // uart_tx.
    input logic tx_busy,
    output logic [7:0] tx_data,
    output logic tx_send
);
    // Registers.
    logic [255:0] key_r;
    logic [ 95:0] nonce_r;
    logic [ 31:0] ctr_r;
    logic [  7:0] cmd_r;
    logic [  7:0] payload_cnt;
    logic [  7:0] byte_offset;
    logic [  7:0] blocks_left;
    logic [ 15:0] crypt_len;
    logic [  7:0] ks_byte;
    logic [  6:0] ks_idx;

    // Command Constants.
    localparam logic [7:0] CMD_LOAD_KEY = 8'h01;
    localparam logic [7:0] CMD_LOAD_NONCE = 8'h02;
    localparam logic [7:0] CMD_LOAD_CTR = 8'h03;
    localparam logic [7:0] CMD_GEN = 8'h04;
    localparam logic [7:0] CMD_CRYPT = 8'h05;

    // FSM.
    typedef enum logic [2:0] {
        IDLE,
        RX_PAYLOAD,
        RX_LEN,
        APPLY,
        RUN_GEN,
        STREAM_GEN,
        RUN_CRYPT,
        CRYPT_DATA
    } state_t;
    state_t fsm;

    // Routing.
    assign busy = (fsm != IDLE);

    assign core_key = key_r;
    assign core_nonce = nonce_r;
    assign core_counter = ctr_r;

    // keystream block.
    assign ks_byte = core_block[8*ks_idx+:8];

    // Main.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            fsm <= IDLE;
            err <= 1'b0;
        end else begin
            core_start <= 1'b0;
            tx_send <= 1'b0;
            case (fsm)
                IDLE: begin
                    if (rx_valid) begin
                        cmd_r <= rx_data;
                        byte_offset <= 0;
                        case (rx_data)
                            CMD_LOAD_KEY: begin
                                payload_cnt <= 32;
                                fsm <= RX_PAYLOAD;
                            end
                            CMD_LOAD_NONCE: begin
                                payload_cnt <= 12;
                                fsm <= RX_PAYLOAD;
                            end
                            CMD_LOAD_CTR: begin
                                payload_cnt <= 4;
                                fsm <= RX_PAYLOAD;
                            end
                            CMD_GEN: begin
                                payload_cnt <= 1;
                                fsm <= RX_PAYLOAD;
                            end
                            CMD_CRYPT: begin
                                fsm <= RX_LEN;
                            end
                            default: begin
                                err <= 1'b1;
                            end
                        endcase
                    end
                end
                RX_PAYLOAD: begin
                    if (rx_valid) begin
                        case (cmd_r)
                            CMD_LOAD_KEY: begin
                                key_r[8*byte_offset+:8] <= rx_data;
                            end
                            CMD_LOAD_NONCE: begin
                                nonce_r[8*byte_offset+:8] <= rx_data;
                            end
                            CMD_LOAD_CTR: begin
                                ctr_r[8*byte_offset+:8] <= rx_data;
                            end
                            CMD_GEN: begin
                                blocks_left <= rx_data;
                            end
                            default: begin
                                err <= 1'b1;
                            end
                        endcase
                        byte_offset <= byte_offset + 1;
                        payload_cnt <= payload_cnt - 1;
                        if (payload_cnt == 1) begin
                            fsm <= APPLY;
                        end
                    end
                end
                RX_LEN: begin
                end
                APPLY: begin
                end
                RUN_GEN: begin
                end
                STREAM_GEN: begin
                end
                RUN_CRYPT: begin
                end
                CRYPT_DATA: begin
                end
                default: fsm <= IDLE;
            endcase
        end
    end
endmodule
