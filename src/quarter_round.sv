/*
 * Copyright (c) 2026 Raphael Eguchi
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module quarter_round (
    input logic [31:0] a_in,
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

    logic [31:0] a, b, c, d;

    always_comb begin
        a = a_in;
        b = b_in;
        c = c_in;
        d = d_in;

        a = a + b;
        d = rotl(d ^ a, 16);
        c = c + d;
        b = rotl(b ^ c, 12);
        a = a + b;
        d = rotl(d ^ a, 8);
        c = c + d;
        b = rotl(b ^ c, 7);

        a_out = a;
        b_out = b;
        c_out = c;
        d_out = d;
    end

endmodule
