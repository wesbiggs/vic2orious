# v2i.inc: displaying .v2i images

`asm/v2i.inc` displays a [.v2i image](v2i-format.md) from your own C64 program and gives
the machine back afterwards. It is ca65 source:

```
        .include "v2i.inc"
```

It doesn't need `v2t.inc`. To draw text beside the image, include both: `v2t.inc`'s
defaults match v2i's screen layout ([v2t-lib.md](v2t-lib.md)). `asm/v2i-demo.s` is the
smallest complete program; assembled with `DUAL=1` it embeds a PAL and an NTSC `.v2i`
and passes `v2i_show` the one that matches `v2i_system`. `asm/slideshow.s`, `asm/diskshow.s`, `asm/viewer.s` and
`asm/ask.s` use both libraries.

Zero page: `$02` (used by the kernels; can't be moved) and `V2I_ZP_SIZE` = 13 bytes from
`V2I_ZP`, default `$10`. Define `V2I_ZP` before the include to move them.

## Lifecycle

```
        jsr v2i_init                    ; take over the machine (once)
        lda #<image                     ; any address outside $c000-$ffff
        ldy #>image
        jsr v2i_show                    ; unpack into VIC bank 3
        bcs error                       ; not shown: jsr v2i_exit, v2i_errmsg says why
        jsr v2i_start                   ; image on screen, raster IRQ running
        ...                             ; your program; v2i_hook runs every frame
        jsr v2i_stop                    ; then v2i_show another image, v2i_start ...
        jsr v2i_exit                    ; or give everything back to the KERNAL
```

## Routines

A/Y = address means A = low byte, Y = high byte. All routines may change A, X and Y.

| routine | input | does |
|---|---|---|
| `v2i_init` | | `SEI`, ROMs out (`$01` = `$35`), CIA interrupts off, VIC bank 3, own IRQ/NMI vectors. Saves `$d000-$d02e`, `$dd00`/`$dd02` and `$01` for `v2i_exit`. Detects the video system (`v2i_system`, up to one frame). |
| `v2i_detect` | | Sets `v2i_system` (see below) from the last raster line: up to one frame, interrupts held off meanwhile. Works with the KERNAL on too, before `v2i_init`, for example to pick which file to load. `v2i_init` calls it. |
| `v2i_show` | A/Y = `.v2i` | Clears `$c000-$feff`, unpacks the image, points the IRQ at its kernel and sets the image info. Only while stopped. C=1: not shown, A = `V2I_ERR_FORMAT` (not a version 3 `.v2i`) or `V2I_ERR_SYSTEM` (the file is for the other video system, or the machine's VIC-II is not supported). |
| `v2i_errmsg` | A = error | A/Y = a zero-terminated PETSCII message for an error from `v2i_show`, such as "THIS IMAGE IS FOR AN NTSC C64". Print it after `v2i_exit` (KERNAL `CHROUT`). |
| `v2i_frame` | A = colour | Draws the 4 px frame (white, white, black, white) into the ring of cells around the image, in cell colour A (`$10`: white on black). Does nothing if the ring doesn't fit on the screen. |
| `v2i_start` | | Border and background black, raster IRQ at line 9 (`V2I_IRQ_LINE`), `CLI`. The image is displayed from the next frame on. |
| `v2i_stop` | | `SEI`, IRQ off, sprites off, screen blanked. |
| `v2i_exit` | | `v2i_stop`, then restores what `v2i_init` saved (sprite registers, colours, mode, bank, `$01`), turns the CIA1 timer IRQ back on for the KERNAL, and does a `CLI`. |

## Variables

- **Image info**, set by `v2i_show`: `v2i_cols` and `v2i_rows` (size in cells),
  `v2i_col` and `v2i_row` (position), and `v2i_end` (the first raster line below the
  image, about where the kernel returns).
- **`v2i_ticks`** counts frames (50 a second on PAL, 60 on NTSC).
- **`v2i_system`**, set by `v2i_detect` (and `v2i_init`): `V2I_PAL` (0: 6569 or 8565, 312 lines), `V2I_NTSC`
  (1: 6567R8 or 8562, 263 lines) or `V2I_OTHER` (`$ff`: anything else, such as the early
  NTSC 6567R56A). `v2i_init` reads it off the last raster line, so a PAL-N (Drean 6572,
  312 lines of 65 cycles) counts as PAL and its images won't display correctly.
- **`v2i_hook`** is a vector called once per frame from the IRQ, right after the kernel.
  The default is an `RTS`. The hook may change A/X/Y. It mustn't call routines that your
  main program might be in the middle of (such as the v2t routines, which share their
  zero page).

## While the image is displayed

The kernel takes the CPU from raster line 9 down to `v2i_end` in every frame. The rest is
yours: for a 128-line image at the top that's about 140 of 312 lines on PAL, roughly 45%
of the machine, and about 90 of 263 lines on NTSC. A 200-line image leaves about 20
lines on NTSC. Your main program just runs and gets interrupted.

- **Text:** the v2t routines are safe to call while the image is displayed. The `ask`
  demo draws all its text that way.
- **Keyboard:** read the CIA1 matrix directly (`$dc00` columns out, `$dc01` rows in). The
  KERNAL is switched out, so there's no `GETIN`. See `scan` in `asm/ask.s`.
- **Music and timing:** call a SID player from `v2i_hook`, and use `v2i_ticks` for delays.
- **Not possible:** KERNAL calls such as `LOAD` and `CHROUT` (`v2i_stop` and switch `$01`
  back first), and sprites of your own (the kernel uses all eight). Don't keep interrupts
  disabled across line 9, or the kernel misses that frame.
- **Any instruction is fine** in the main program: the kernel's entry window allows for
  the longest 6502 instructions.
