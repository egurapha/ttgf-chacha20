/*
 * Copyright (c) 2026 Raphael Eguchi
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module chacha20_core (
    // Input.
    input logic clk,
    input logic rst_n,
    input logic [255:0] key,
    input logic [95:0] nonce,
    input logic [31:0] counter,
    input logic start,
    // Output.
    output logic done,
    output logic [511:0] block  // keystream block.
);
    // Registers.
    logic [31:0] s[16];  // 32 bits, 16 element state matrix.
    logic [31:0] iw[16];
    logic [4:0] step;  // counter for the number of quarter rounds.
    logic done_r;
    assign done = done_r;

    // Constants.
    localparam logic [31:0] C0 = 32'h61707865;
    localparam logic [31:0] C1 = 32'h3320646e;
    localparam logic [31:0] C2 = 32'h79622d32;
    localparam logic [31:0] C3 = 32'h6b206574;

    // FSM.
    typedef enum logic [2:0] {
        IDLE,
        INIT,
        ROUND,
        DONE
    } state_t;
    state_t fsm;

    // Quarter Round Wires.
    logic [31:0] a0_in, b0_in, c0_in, d0_in, a0_out, b0_out, c0_out, d0_out;
    logic [31:0] a1_in, b1_in, c1_in, d1_in, a1_out, b1_out, c1_out, d1_out;
    logic [31:0] a2_in, b2_in, c2_in, d2_in, a2_out, b2_out, c2_out, d2_out;
    logic [31:0] a3_in, b3_in, c3_in, d3_in, a3_out, b3_out, c3_out, d3_out;

    // Quarter Round Modules.
    quarter_round qr0 (
        .a_in (a0_in),
        .b_in (b0_in),
        .c_in (c0_in),
        .d_in (d0_in),
        .a_out(a0_out),
        .b_out(b0_out),
        .c_out(c0_out),
        .d_out(d0_out)
    );
    quarter_round qr1 (
        .a_in (a1_in),
        .b_in (b1_in),
        .c_in (c1_in),
        .d_in (d1_in),
        .a_out(a1_out),
        .b_out(b1_out),
        .c_out(c1_out),
        .d_out(d1_out)
    );
    quarter_round qr2 (
        .a_in (a2_in),
        .b_in (b2_in),
        .c_in (c2_in),
        .d_in (d2_in),
        .a_out(a2_out),
        .b_out(b2_out),
        .c_out(c2_out),
        .d_out(d2_out)
    );
    quarter_round qr3 (
        .a_in (a3_in),
        .b_in (b3_in),
        .c_in (c3_in),
        .d_in (d3_in),
        .a_out(a3_out),
        .b_out(b3_out),
        .c_out(c3_out),
        .d_out(d3_out)
    );

    // Routing.
    always_comb begin
        // Initial State Addition.
        // build wire matrix.
        iw[0]  = C0;
        iw[1]  = C1;
        iw[2]  = C2;
        iw[3]  = C3;
        iw[12] = counter;
        for (int i = 0; i < 8; i++) begin
            iw[4+i] = key[32*i+:32];
        end
        iw[12] = counter;
        for (int i = 0; i < 3; i++) begin
            iw[13+i] = nonce[32*i+:32];
        end
        // add to state.
        for (int i = 0; i < 16; i++) begin
            block[32*i+:32] = s[i] + iw[i];
        end

        // Quarter Round.
        if (!step[0]) begin  // if even, do columns.
            a0_in = s[0];
            b0_in = s[4];
            c0_in = s[8];
            d0_in = s[12];
            a1_in = s[1];
            b1_in = s[5];
            c1_in = s[9];
            d1_in = s[13];
            a2_in = s[2];
            b2_in = s[6];
            c2_in = s[10];
            d2_in = s[14];
            a3_in = s[3];
            b3_in = s[7];
            c3_in = s[11];
            d3_in = s[15];
        end else begin  // if odd step, do diagonals.
            a0_in = s[0];
            b0_in = s[5];
            c0_in = s[10];
            d0_in = s[15];
            a1_in = s[1];
            b1_in = s[6];
            c1_in = s[11];
            d1_in = s[12];
            a2_in = s[2];
            b2_in = s[7];
            c2_in = s[8];
            d2_in = s[13];
            a3_in = s[3];
            b3_in = s[4];
            c3_in = s[9];
            d3_in = s[14];
        end
    end

    // Main.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            fsm <= IDLE;
            done_r <= 1'b0;
        end else begin
            case (fsm)
                IDLE: begin
                    if (start) fsm <= INIT;
                end
                INIT: begin
                    // Initialize State Matrix.
                    // Constants.
                    s[0] <= C0;
                    s[1] <= C1;
                    s[2] <= C2;
                    s[3] <= C3;
                    // Keys.
                    for (int i = 0; i < 8; i++) begin
                        s[4+i] <= key[32*i+:32];
                    end
                    // Counter.
                    s[12] <= counter;
                    // Nonce.
                    for (int i = 0; i < 3; i++) begin
                        s[13+i] <= nonce[32*i+:32];
                    end
                    // Set step to 0.
                    step <= 5'd0;
                    // Start applying quarter rounds.
                    fsm <= ROUND;
                    // Not Done.
                    done_r <= 1'b0;
                end
                ROUND: begin
                    if (!step[0]) begin  // if even, do columns.
                        s[0]  <= a0_out;
                        s[4]  <= b0_out;
                        s[8]  <= c0_out;
                        s[12] <= d0_out;
                        s[1]  <= a1_out;
                        s[5]  <= b1_out;
                        s[9]  <= c1_out;
                        s[13] <= d1_out;
                        s[2]  <= a2_out;
                        s[6]  <= b2_out;
                        s[10] <= c2_out;
                        s[14] <= d2_out;
                        s[3]  <= a3_out;
                        s[7]  <= b3_out;
                        s[11] <= c3_out;
                        s[15] <= d3_out;
                    end else begin  // if odd, do diagonals.
                        s[0]  <= a0_out;
                        s[5]  <= b0_out;
                        s[10] <= c0_out;
                        s[15] <= d0_out;
                        s[1]  <= a1_out;
                        s[6]  <= b1_out;
                        s[11] <= c1_out;
                        s[12] <= d1_out;
                        s[2]  <= a2_out;
                        s[7]  <= b2_out;
                        s[8]  <= c2_out;
                        s[13] <= d2_out;
                        s[3]  <= a3_out;
                        s[4]  <= b3_out;
                        s[9]  <= c3_out;
                        s[14] <= d3_out;
                    end
                    step <= step + 5'd1;
                    if (step == 5'd19) begin
                        fsm <= DONE;  // 20 steps x 4 rounds.
                    end
                end
                DONE: begin
                    done_r <= 1'b1;
                    if (start) fsm <= INIT;
                end
                default: fsm <= IDLE;
            endcase
        end
    end
endmodule
