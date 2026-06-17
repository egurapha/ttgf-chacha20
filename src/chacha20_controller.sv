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
    input logic [31:0] core_block_word,  // selected keystream word from the core
    output logic [3:0] core_word_idx,    // which 32-bit word to read
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
    logic [95:0] nonce_r;
    logic [31:0] ctr_r;
    logic [7:0] cmd_r;
    logic [7:0] payload_cnt;
    logic [7:0] byte_offset;  // index of the current payload byte.
    logic [7:0] blocks_left;
    logic [15:0] crypt_len;
    logic [7:0] ks_byte;
    logic [6:0] ks_idx;
    logic [7:0] d_in;  // latched incoming data byte.
    logic pending;  // if 1, we have a latched byte that is not sent yet.
    logic done_prev;

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

    // keystream byte: ask the core for the word (ks_idx[5:2]), then pick the
    // byte within it (ks_idx[1:0]): a small 4:1 mux instead of a 64:1 on 512 bits.
    assign core_word_idx = ks_idx[5:2];
    assign ks_byte = core_block_word[8*ks_idx[1:0]+:8];

    // Main.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            fsm <= IDLE;
            err <= 1'b0;
            done_prev <= 1'b0;
            pending <= 1'b0;
            core_start  <= 1'b0;
            tx_send     <= 1'b0;
            tx_data     <= '0;
            cmd_r       <= '0;
            payload_cnt <= '0;
            byte_offset <= '0;
            blocks_left <= '0;
            crypt_len   <= '0;
            ks_idx      <= '0;
            d_in        <= '0;
        end else begin
            core_start <= 1'b0;
            tx_send <= 1'b0;
            done_prev <= core_done;
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
                                key_r <= {rx_data, key_r[255:8]};
                            end
                            CMD_LOAD_NONCE: begin
                                nonce_r <= {rx_data, nonce_r[95:8]};
                            end
                            CMD_LOAD_CTR: begin
                                ctr_r <= {rx_data, ctr_r[31:8]};
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
                    // process length in little endian order. 2 bytes.
                    if (rx_valid) begin
                        if (byte_offset == 0) begin
                            crypt_len[7:0] <= rx_data;
                            byte_offset <= 1;
                        end else begin
                            crypt_len[15:8] <= rx_data;
                            fsm <= APPLY;
                        end
                    end
                end
                APPLY: begin
                    case (cmd_r)
                        CMD_LOAD_KEY: begin
                            fsm <= IDLE;
                        end
                        CMD_LOAD_NONCE: begin
                            fsm <= IDLE;
                        end
                        CMD_LOAD_CTR: begin
                            fsm <= IDLE;
                        end
                        CMD_GEN: begin
                            if (blocks_left == 0) begin
                                fsm <= IDLE;
                            end else begin
                                ks_idx <= 0;
                                core_start <= 1'b1;
                                fsm <= RUN_GEN;
                            end
                        end
                        CMD_CRYPT: begin
                            if (crypt_len == 0) begin
                                fsm <= IDLE;
                            end else begin
                                ks_idx <= 0;
                                core_start <= 1'b1;
                                fsm <= RUN_CRYPT;
                            end
                        end
                        default: begin
                            err <= 1'b1;
                        end
                    endcase
                end
                RUN_GEN: begin
                    // wait until the core_block is computed by checking for
                    // core_done == 1. make sure done_prev == 0 to account for
                    // the core_done being held high within the core.
                    if (core_done && !done_prev) begin
                        fsm <= STREAM_GEN;
                    end
                end
                STREAM_GEN: begin
                    if (ks_idx < 64) begin
                        if (!tx_busy && !tx_send) begin
                            tx_data <= ks_byte;
                            tx_send <= 1'b1;  // gets reset to 0 in the top else.
                            ks_idx  <= ks_idx + 1;
                        end
                    end else begin  // if ks_idx == 64, completed block.
                        if (blocks_left > 1) begin
                            ctr_r <= ctr_r + 1;  // advance core counter.
                            blocks_left <= blocks_left - 1;
                            ks_idx <= 0;  // reset byte index in the keystream.
                            core_start <= 1'b1;  // start next block generation.
                            fsm <= RUN_GEN;  // wait until core_done.
                        end else begin
                            // if blocks_left == 1, we've already delivered
                            // that block, so we are done.
                            fsm <= IDLE;
                        end
                    end
                end
                RUN_CRYPT: begin
                    // Hold a data byte that arrives during the block recompute.
                    // CRYPT has no separate input buffer; pending/d_in double as a
                    // 1-byte holding register, so a fast parallel host
                    // streaming across a 64-byte boundary does not lose this byte.
                    if (rx_valid && !pending) begin
                        d_in    <= rx_data;
                        pending <= 1'b1;
                    end
                    if (core_done && !done_prev) begin
                        fsm <= CRYPT_DATA;
                    end
                end
                CRYPT_DATA: begin
                    if (ks_idx == 64) begin  // block complete.
                        ctr_r <= ctr_r + 1;
                        ks_idx <= 0;
                        core_start <= 1'b1;
                        fsm <= RUN_CRYPT;
                    end else if (pending) begin
                        if (!tx_busy && !tx_send) begin
                            tx_data <= d_in ^ ks_byte;  // XOR.
                            tx_send <= 1'b1;
                            ks_idx <= ks_idx + 1;
                            crypt_len <= crypt_len - 1;
                            pending <= 1'b0;  // mark data as sent.
                            if (crypt_len == 1) begin
                                fsm <= IDLE;
                            end
                        end
                    end else if (rx_valid) begin
                        d_in <= rx_data;
                        pending <= 1'b1;
                    end
                end
                default: fsm <= IDLE;
            endcase
        end
    end
endmodule
