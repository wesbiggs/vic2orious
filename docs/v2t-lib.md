# v2t.inc: proportional text on a hires bitmap

`asm/v2t.inc` draws [.v2t text files](v2t-format.md) and single lines of text into a
hires bitmap, with the proportional font from `font.inc` (a GEOS font record, see
[v2t-format.md](v2t-format.md#the-font)). It is ca65 source:

```
        .include "v2t.inc"              ; needs font.inc (written by python3 -m vic2.build)
                                        ; on the include path
```

It doesn't need `v2i.inc`, and it doesn't set up the VIC. Your program chooses the
bitmap and screen (colour) memory and switches on hires bitmap mode. With `v2i.inc` that
has already happened.

| define before the include | default | |
|---|---|---|
| `V2T_BITMAP` | `$e000` | 8000-byte bitmap (v2i's) |
| `V2T_SCREEN` | `$c000` | 1000 cell colours (v2i's screen) |
| `V2T_ZP` | `$1d` | `V2T_ZP_SIZE` = 10 zero page bytes (just after v2i's default block) |

Glyphs are OR'd into the bitmap, so the CPU must read the bitmap back as RAM: if it sits
under a ROM, bank that ROM out. `asm/v2t-demo.s` keeps the KERNAL running and puts the
bitmap in VIC bank 1 (`$6000`, colours at `$4400`).

## Routines

A/Y = address means A = low byte, Y = high byte. All routines may change A, X and Y.
Text is character codes 32-127, ASCII ([v2t-format.md](v2t-format.md)); ca65 `.byte "..."`
strings work as they are. H below is the font's height, `V2T_FONT_H` (8 for the ROM font).
Colours are cell colours, `fg << 4 | bg`: `$f0` is light grey on black.

| routine | input | does |
|---|---|---|
| `v2t_draw` | A/Y = `.v2t` | Draws the text file at the column, row and leading in its header. C=1: not a `.v2t`, or laid out for a font of another height. |
| `v2t_draw_at` | A/Y = `.v2t` | The same, at pixel `v2t_x`, `v2t_y` with leading `v2t_lead`. The area starts at cell `v2t_x / 8`, so a position that isn't cell aligned leaves less room at the right. |
| `v2t_line` | A/Y = text | One line, ending in a 0 byte: clears the H pixel lines at `v2t_y` across `v2t_cols` cells starting at cell `v2t_x / 8`, colours those cells `v2t_color` (every character row the H lines touch), draws the text from pixel `v2t_x`, then adds `H + v2t_lead` to `v2t_y`. C=1: the text was clipped at the right edge. |
| `v2t_measure` | A/Y = text | Pixel width of the line: A = low byte, X = high byte. |
| `v2t_clear` | A = colour | Clears `v2t_cols` x `v2t_rows` cells from `v2t_col`, `v2t_row` (bitmap 0, cell colour A). |
| `v2t_paint` | A = colour | Colours the same cells as `v2t_clear` (cell colour A) and leaves the bitmap as it is: recolours text without drawing it again. |

`v2t_draw` and `v2t_draw_at` OR into whatever is already there, so `v2t_clear` the area
before drawing over old text. `v2t_line` clears its own H lines, and it colours all
`v2t_cols` cells, so a background colour fills the line evenly to the right. Text below row 24, and glyphs past the right edge
of the cells, are cut off.

## Parameters

`v2t_x` (word), `v2t_y`, `v2t_lead` (default 2), `v2t_color` (default `$f0`), `v2t_col`,
`v2t_row`, `v2t_cols` (default 40), `v2t_rows`.

Patterns: to centre a line, take `(320 - v2t_measure) / 2` as `v2t_x`. To right-align it,
subtract the width from the right edge (`asm/v2t-demo.s` does both). For a column of
lines, set `v2t_y` once and call `v2t_line` repeatedly.
