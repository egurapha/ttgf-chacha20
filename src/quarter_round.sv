/*
 * Copyright (c) 2026 Raphael Eguchi
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module quarter_round (
    input  logic [ 1:0] stage,  // 4 stages. 0 to 3.
    input  logic [31:0] a_in,
    b_in,
    c_in,
    d_in,
    output logic [31:0] a_out,
    b_out,
    c_out,
    d_out
);
    function automatic [31:0] rotl(input logic [31:0] x, input integer n);
        rotl = (x << n) | (x >> (32 - n));
    endfunction

    // One parallel-prefix adder per quarter-round, operands selected by stage:
    //   even stages (0,2) compute a+b;  odd stages (1,3) compute c+d.
    logic [31:0] add_x, add_y, add_s;
    assign add_x = stage[0] ? c_in : a_in;
    assign add_y = stage[0] ? d_in : b_in;
    adder32 u_add (
        .a  (add_x),
        .b  (add_y),
        .sum(add_s)
    );

    always_comb begin
        // Default: pass inputs through (covers the unchanged words each stage
        // and the unreachable default case).
        a_out = a_in;
        b_out = b_in;
        c_out = c_in;
        d_out = d_in;
        case (stage)
            2'd0: begin
                a_out = add_s;
                d_out = rotl(d_in ^ add_s, 16);
            end
            2'd1: begin
                c_out = add_s;
                b_out = rotl(b_in ^ add_s, 12);
            end
            2'd2: begin
                a_out = add_s;
                d_out = rotl(d_in ^ add_s, 8);
            end
            2'd3: begin
                c_out = add_s;
                b_out = rotl(b_in ^ add_s, 7);
            end
            default: ;  // pass-through (outputs already = inputs)
        endcase
    end

endmodule
