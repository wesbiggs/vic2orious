# .v2i image format (version 3)

A `.v2i` file holds one converted image: a hires bitmap, its cell colours, the sprite data,
and a *kernel*. The kernel is 6502 code generated for this image that rewrites the sprite
registers on every raster line, so the sprites paint the pixels the bitmap can't.
`vic2/build.py` writes it, and `asm/v2i.inc` displays it ([v2i-lib.md](v2i-lib.md)).

On disk it is a PRG file with load address `$2000`. The contents don't depend on where
they're loaded, so a program can load the file anywhere outside `$c000-$ffff` and pass
that address to `v2i_show`.

## Layout

All words are little endian. Offsets are from the start of the data, after the PRG's
2-byte load address.

| offset | size | field |
|---|---|---|
| 0 | 3 | magic `"V2I"` |
| 3 | 1 | format version, 3 |
| 4 | 1 | width in cells (width / 8) |
| 5 | 1 | height in cells (height / 8) |
| 6 | 1 | character column of the image's left edge |
| 7 | 1 | character row of the image's top edge |
| 8 | 2 | kernel length |
| 10 | 2 | bitmap stream length |
| 12 | 2 | screen stream length |
| 14 | 2 | sprite stream length |
| 16 | 2 | bitmap destination: `$e000 + 320 * row` |
| 18 | 2 | screen destination: `$c000 + 40 * row` |
| 20 | 2 | number of image lines that are not pixel perfect (information only) |
| 22 | 2 | number of image pixels that are not pixel perfect (information only) |
| 24 | 1 | video system the kernel is made for: 0 PAL (6569/8565, 63 cycles x 312 lines), 1 NTSC (6567R8/8562, 65 cycles x 263 lines) |
| 25 | 1 | reserved, 0 |
| 26 | ... | kernel, then the bitmap, screen and sprite streams, back to back |

Version 2 kernels were entered on raster line 2 (same layout). Version 1 had no video
system byte (always PAL) and a 24-byte header.

## Streams

All three streams are **zero-run encoded**: `$00, n` stands for n zero bytes (n =
1..255), any other byte is itself, and `$00, $00` ends the stream.

- **Bitmap:** whole 320-byte screen rows, one per character row the image covers. They
  decode straight to the bitmap destination, so cells outside the image are 0.
- **Screen:** whole 40-byte rows of cell colours, `fg << 4 | bg`, decoded to the screen
  destination.
- **Sprites:** 64-byte sprite blocks, decoded to `$c400` (sprite pointer 16). Block 16 is
  all zero; the kernel points sprites at it outside the image. The stream holds as many
  blocks as the image uses. Each block holds one 21-line stretch of one sprite.

## Kernel

The kernel is an unrolled, cycle-exact routine, called with `JSR` once per frame. It
only works on the video system in byte 24: on the other one every write lands at the
wrong cycle (`v2i_show` refuses such a file). The sprite and bitmap data are converted
together with the kernel, so they differ between PAL and NTSC files too. It assumes:

- **Screen layout:** VIC bank 3 (`$c000-$ffff`), with the screen at `$c000`, sprite
  pointers at `$c3f8` and the bitmap at `$e000`. It sets `$d011` = `$3b`, `$d016` = `$08` and
  `$d018` = `$08`, but doesn't select the bank itself or touch the border and background
  colours (`v2i_start` sets them to black: a colour write leaves a grey dot on the 85xx,
  and the kernel's first lines are visible on NTSC).
- **Entry time:** it is entered on raster line 9, between cycles 20 and 47 of that line.
  Line 9 is below the sprite DMA that can still be running from the previous frame:
  `$d015` = 0 does not stop a sprite's 21-line block, and on NTSC (263 lines) the blocks
  of a 200-line image run on to line 8. `v2i.inc`'s IRQ handler (raster IRQ at line 9, then `STA`/`STX`/`STY` to zero page,
  `JSR`, `JMP (vector)`) gets there from any interrupted instruction. The kernel's first
  instructions sync to the exact cycle, so the entry time can vary within that window.
- **No DMA surprises:** nothing else may change VIC registers or steal cycles while it
  runs.
- **What it touches:** zero page `$02` (scratch for the sync code), VIC registers and the
  sprite pointers. Nothing else, and it doesn't depend on where it is in memory.

It turns all 8 sprites on, rewrites their position, colour and pointer registers line by
line down to the image's last line, sets `$d015` = 0, and returns with `RTS` at about
raster line `$33 + 8 * (row + height)`. Their X high bits (`$d010`) stay 0.

The image's position is part of the kernel: every write is timed for that column and row.
To show an image somewhere else, convert it again with `build --at COLUMN,ROW`. The image
must start at column 28 or less, because sprite X stays below 256.
