/*
 * Copyright (c) 2026 Raphael Eguchi
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// 32-bit parallel-prefix (Kogge-Stone) adder, carry-in = 0.
// The carry resolves in ~log2(32) = 5 prefix levels instead of the ~32-deep
// ripple-carry chain the synthesizer inferred for the plus operator (which the
// ss-corner timing report showed as the critical path). Purely combinational.
module adder32 (
    input  logic [31:0] a,
    input  logic [31:0] b,
    output logic [31:0] sum
);
    logic [31:0] g, p;     // bit generate / propagate
    logic [31:0] gg, pp;   // running prefix generate / propagate
    logic [31:0] gn, pn;   // next prefix level
    integer i, lvl, off;

    always_comb begin
        for (i = 0; i < 32; i++) begin
            g[i] = a[i] & b[i];
            p[i] = a[i] ^ b[i];
        end
        gg = g;
        pp = p;
        // Kogge-Stone prefix: 5 levels, offsets 1, 2, 4, 8, 16.
        for (lvl = 0; lvl < 5; lvl = lvl + 1) begin
            off = 1 << lvl;
            for (i = 0; i < 32; i++) begin
                if (i >= off) begin
                    gn[i] = gg[i] | (pp[i] & gg[i-off]);
                    pn[i] = pp[i] & pp[i-off];
                end else begin
                    gn[i] = gg[i];
                    pn[i] = pp[i];
                end
            end
            gg = gn;
            pp = pn;
        end
        // carry into bit i = group-generate up to bit i-1 (cin = 0).
        sum[0] = p[0];
        for (i = 1; i < 32; i++) sum[i] = p[i] ^ gg[i-1];
    end
endmodule
