; v2t scroll demo: a page of text taller than the screen, scrolled smoothly, one pixel per
; frame, with cursor down / cursor up (shift + cursor down) or a joystick in port 2. Space
; returns to BASIC.
;
; Two bitmaps, A ($6000, colours $4000, VIC bank 1) and B ($a000, colours $8000, bank 2):
; one is shown (front), the other is prepared (back). The VIC's fine scroll ($d011 bits
; 0-2, s) moves the front 0-7 pixels; past that the IRQ shows the back instead, if it holds
; the page one char row further: base (page pixel line in row 0) +- 8. The main loop
; prepares it: the colours of the rows whose colour changes (each row has one, from
; scr_rc), 24 char rows of bitmap copied from the front, one row up or down, and the new
; row drawn with v2t (cleared, then every line that touches it, clipped to that row and
; ORed in: v2t_over). Until it is ready the scroll waits. 24-row mode: the screen shows page lines v..v+191, v =
; base + 7 - s; rows 0 and 24 are only partly visible.
;
; Assembled with AUTO=1 (build --verify) it scrolls down to page line AUTO_V1, then up to
; AUTO_V2 by itself, and stays there. With AUTO=2 it asks for AUTO_N pixels down, one per
; frame (after 10 frames): it ends at page line AUTO_N only if preparing never made the
; scroll wait.

        .include "scroll.inc"           ; generated: the page (lines, colours, row tables)

.ifndef AUTO
AUTO = 0
.endif

BMP_A   = $6000
SCR_A   = $4000
BMP_B   = $a000
SCR_B   = $8000
VOFF    = 4                             ; v2t draws 4 rows lower, at a bitmap 4 rows early,
                                        ; so lines may start up to 32 pixels above row 0
IRQ_LN  = 250                           ; below the last visible line in both systems

p       = $fb                           ; 2 bytes each: pointers
q       = $fd
z       = $57                           ; (BASIC's float scratch)

        .segment "LOADADDR"
        .word $0801
        .segment "EXEHDR"
        .word @next, 10
        .byte $9e, "2061", 0
@next:  .word 0

        .code
start:  sei
        lda #$36                        ; BASIC off: bitmap B is under it
        sta $01
        lda #1                          ; lines are ORed into a cleared row
        sta v2t_over
        ldx #0                          ; the first page into A, rows 0-24
        stx front
        stx rr
        stx pb
        stx pb+1
        jsr colours
@first: ldx #0
        lda rr
        jsr render
        inc rr
        lda rr
        cmp #25
        bne @first

        lda #$7f                        ; IRQ: raster line IRQ_LN only
        sta $dc0d
        lda $dc0d
        lda #<irq
        sta $0314
        lda #>irq
        sta $0315
        lda #IRQ_LN
        sta $d012
        lda #$37                        ; bitmap, 24 rows, s = 7 (raster bit 8 = 0)
        sta $d011
        lda #$08                        ; screen at +$0000, bitmap at +$2000
        sta $d018
        lda #0
        sta $d020
        lda $dd02
        ora #$03
        sta $dd02
        ldx #0
        jsr bank
        lda #1
        sta $d01a
        asl $d019
        cli

; prepare the back for the direction scrolled last, until it is what the IRQ needs
main:   lda quit
        beq :+
        jmp exit
:       sei
        lda dir
        bmi @up
        clc                             ; down: base + 8, if the scroll can get there
        lda base
        adc #8
        sta pb
        lda base+1
        adc #0
        sta pb+1
        lda #<SCR_VMAX
        cmp pb
        lda #>SCR_VMAX
        sbc pb+1
        bcc @idle                       ; vmax < base + 8
        bcs @need
@up:    lda base                        ; up: base - 8, if base > 0
        ora base+1
        beq @idle
        sec
        lda base
        sbc #8
        sta pb
        lda base+1
        sbc #0
        sta pb+1
@need:  lda pb
        cmp btag
        bne :+
        lda pb+1
        cmp btag+1
        beq @idle                       ; the back holds it
:       lda #$ff                        ; the back is being changed: no swap until done
        sta btag
        sta btag+1
        lda dir
        sta pdir
        lda front
        sta pfront
        cli
        jsr prepare
        lda dir                         ; turned meanwhile: start over
        cmp pdir
        bne main
        sei
        lda pb
        sta btag
        lda pb+1
        sta btag+1
@idle:  cli
        jmp main

; the back (1 - pfront) for base pb: colours, copy the front shifted one row, new row
prepare:
        lda pfront
        eor #1
        tax
        jsr colours
        lda pdir
        bmi @up
        lda pfront                      ; down: rows 1-24 to 0-23, draw row 24
        bne :+
        jsr copy_ab_down
        jmp @d
:       jsr copy_ba_down
@d:     lda dir                         ; turned: drawing the row is no use
        cmp pdir
        bne @done
        lda pfront
        eor #1
        tax
        lda #24
        jmp render
@up:    lda pfront                      ; up: rows 0-23 to 1-24, draw row 0
        bne :+
        jsr copy_ab_up
        jmp @u
:       jsr copy_ba_up
@u:     lda dir
        cmp pdir
        bne @done
        lda pfront
        eor #1
        tax
        lda #0
        jmp render
@done:  rts

; draw char row A of bitmap X (0: A, 1: B) for base pb: page row pb / 8 + A
render: sta rr
        lsr                             ; clear it: p = bitmap + 320 * rr, q = p + 160
        lsr
        sta p+1
        lda rr
        asl
        asl
        asl
        asl
        asl
        asl
        clc
        adc bmp0lo,x
        sta p
        lda p+1
        adc bmp0hi,x
        clc
        adc rr
        sta p+1
        clc
        lda p
        adc #160
        sta q
        lda p+1
        adc #0
        sta q+1
        lda #0
        ldy #160
:       dey
        sta (p),y
        sta (q),y
        bne :-
        lda bmplo,x                     ; v2t draws VOFF rows lower into a bitmap VOFF
        sta v2t_bitmap                  ; rows early, clipped to row rr + VOFF
        lda bmphi,x
        sta v2t_bitmap+1
        lda scrlo,x
        sta v2t_screen
        lda scrhi,x
        sta v2t_screen+1
        lda rr
        clc
        adc #VOFF
        sta v2t_rtop
        adc #1
        sta v2t_rbot
        jsr prow                        ; j = pb / 8 + rr
        clc
        adc rr
        sta q
        bcc :+
        inc q+1
:       clc                             ; first line and count from the row tables
        lda q
        adc #<scr_first
        sta p
        lda q+1
        adc #>scr_first
        sta p+1
        ldy #0
        lda (p),y
        sta li
        clc
        lda q
        adc #<scr_cnt
        sta p
        lda q+1
        adc #>scr_cnt
        sta p+1
        lda (p),y
        beq @done
        sta ln
@line:  ldx li                          ; y = line's page y - pb + 8 * VOFF (0..255)
        sec
        lda scr_ylo,x
        sbc pb
        clc
        adc #8 * VOFF
        sta v2t_y
        lda scr_clr,x
        sta v2t_color
        lda #<SCR_X
        sta v2t_x
        lda #>SCR_X
        sta v2t_x+1
        lda #SCR_COLS
        sta v2t_cols
        lda scr_tlo,x
        ldy scr_thi,x
        jsr v2t_line
        inc li
        dec ln
        bne @line
@done:  rts

; colour bitmap X's rows for base pb: those whose colour (scr_rc) differs from what they
; show now (for base cb, all if that is unknown)
colours:
        stx cx
        jsr prow                        ; p = scr_rc + pb / 8
        clc
        adc #<scr_rc
        sta p
        lda q+1
        adc #>scr_rc
        sta p+1
        lda #0
        sta call
        lda cbhi,x                      ; q = scr_rc + cb
        sta q+1
        lda cblo,x
        sta q
        and q+1
        cmp #$ff
        bne :+
        dec call                        ; unknown: all of them
:       clc
        lda q
        adc #<scr_rc
        sta q
        lda q+1
        adc #>scr_rc
        sta q+1
        lda scr0lo,x
        sta z
        lda scr0hi,x
        sta z+1
        ldx #0
@row:   txa
        tay
        lda (p),y
        bit call
        bmi :+
        cmp (q),y
        beq @next
:       ldy #39
:       sta (z),y
        dey
        bpl :-
@next:  clc
        lda z
        adc #40
        sta z
        bcc :+
        inc z+1
:       inx
        cpx #25
        bne @row
        ldx cx                          ; cb = pb / 8
        jsr prow
        sta cblo,x
        lda q+1
        sta cbhi,x
        rts

prow:   lda pb+1                        ; A = q = pb / 8 (q+1 high)
        sta q+1
        lda pb
        lsr q+1
        ror
        lsr q+1
        ror
        lsr q+1
        ror
        sta q
        rts

; raster IRQ (through the KERNAL's $0314): one pixel per frame, swap at the row boundary
irq:    asl $d019
.if AUTO
        jsr script
.else
        jsr keys
.endif
        beq @set
        sta dir
        bmi @up
        jsr vpos                        ; down: if v < vmax
        lda iv
        cmp #<SCR_VMAX
        lda iv+1
        sbc #>SCR_VMAX
        bcs @set
        lda fs
        beq :+
        dec fs
        jmp @set
:       clc                             ; s = 0: the back must hold base + 8
        lda base
        adc #8
        sta it
        lda base+1
        adc #0
        sta it+1
        jsr swap
        bne @set
        lda #7
        sta fs
        bne @set
@up:    lda base                        ; up: if v > 0
        ora base+1
        bne :+
        lda fs
        cmp #7
        beq @set
:       lda fs
        cmp #7
        beq :+
        inc fs
        bne @set
:       sec                             ; s = 7: the back must hold base - 8
        lda base
        sbc #8
        sta it
        lda base+1
        sbc #0
        sta it+1
        jsr swap
        bne @set
        lda #0
        sta fs
@set:   lda fs
        ora #$30
        sta $d011
        ldx front
        jsr bank
        jmp $ea81                       ; KERNAL: restore registers, RTI

; if btag = it: show the back, base = it, btag = old base, Z=1; else Z=0
swap:   lda it
        cmp btag
        bne @no
        lda it+1
        cmp btag+1
        bne @no
        lda base
        sta btag
        lda base+1
        sta btag+1
        lda it
        sta base
        lda it+1
        sta base+1
        lda front
        eor #1
        sta front
        lda #0
@no:    rts

vpos:   sec                             ; iv = base + 7 - s
        lda #7
        sbc fs
        clc
        adc base
        sta iv
        lda base+1
        adc #0
        sta iv+1
        rts

bank:   lda $dd00                       ; VIC bank of bitmap X
        and #$fc
        ora banks,x
        sta $dd00
        rts

.if AUTO = 2
script: lda wait                        ; down for AUTO_N frames
        beq :+
        dec wait
        lda #0
        rts
:       lda nf
        ora nf+1
        beq :++
        lda nf
        bne :+
        dec nf+1
:       dec nf
        lda #1
        rts
:       lda #0
        rts
wait:   .byte 10
nf:     .word AUTO_N
.elseif AUTO
script: jsr vpos                        ; down to AUTO_V1, then up to AUTO_V2
        lda phase
        bne @up
        lda iv
        cmp #<AUTO_V1
        lda iv+1
        sbc #>AUTO_V1
        bcs :+
        lda #1
        rts
:       inc phase
@up:    lda #<AUTO_V2
        cmp iv
        lda #>AUTO_V2
        sbc iv+1
        bcs :+
        lda #$ff
        rts
:       lda #0
        rts
phase:  .byte 0
.else
; A = 1: down, $ff: up, 0: neither. Space sets quit
keys:   lda #$7f                        ; space: column 7, row 4
        sta $dc00
        lda $dc01
        and #$10
        bne :+
        inc quit
:       lda #$fe                        ; cursor down: column 0, row 7
        sta $dc00
        lda $dc01
        and #$80
        bne @joy
        lda #$fd                        ; left shift: column 1, row 7
        sta $dc00
        lda $dc01
        and #$80
        beq @u
        lda #$bf                        ; right shift: column 6, row 4
        sta $dc00
        lda $dc01
        and #$10
        beq @u
        lda #1
        rts
@joy:   lda #$ff                        ; joystick 2: bit 0 up, bit 1 down (0 = pressed)
        sta $dc00
        lda $dc00
        lsr
        bcc @u
        lsr
        bcc @d
        lda #0
        rts
@u:     lda #$ff
        rts
@d:     lda #1
        rts
.endif

exit:   sei                             ; back to BASIC's text screen
        lda #0
        sta $d01a
        asl $d019
        lda #<$ea31
        sta $0314
        lda #>$ea31
        sta $0315
        lda #$81
        sta $dc0d
        lda #$1b
        sta $d011
        lda #$15
        sta $d018
        lda $dd00
        ora #$03
        sta $dd00
        lda #14
        sta $d020
        lda #6
        sta $d021
        lda #$37
        sta $01
        cli
        jmp ($a002)                     ; BASIC warm start

; copy 24 char rows of bitmap (7680 bytes) one row up or down
.macro rows src, dst
        ldx #0                          ; 30 pages, in two loops (branch range)
:       .repeat 15, I
        lda src + I * 256,x
        sta dst + I * 256,x
        .endrep
        inx
        bne :-
:       .repeat 15, I
        lda src + (I + 15) * 256,x
        sta dst + (I + 15) * 256,x
        .endrep
        inx
        bne :-
        rts
.endmacro
copy_ab_down: rows BMP_A + 320, BMP_B
copy_ba_down: rows BMP_B + 320, BMP_A
copy_ab_up:   rows BMP_A, BMP_B + 320
copy_ba_up:   rows BMP_B, BMP_A + 320

        .data
bmplo:  .byte <(BMP_A - VOFF * 320), <(BMP_B - VOFF * 320)
bmphi:  .byte >(BMP_A - VOFF * 320), >(BMP_B - VOFF * 320)
scrlo:  .byte <(SCR_A - VOFF * 40), <(SCR_B - VOFF * 40)
scrhi:  .byte >(SCR_A - VOFF * 40), >(SCR_B - VOFF * 40)
bmp0lo: .byte <BMP_A, <BMP_B
bmp0hi: .byte >BMP_A, >BMP_B
scr0lo: .byte <SCR_A, <SCR_B
scr0hi: .byte >SCR_A, >SCR_B
banks:  .byte $02, $01                  ; $dd00 bits: bank 1 ($4000), bank 2 ($8000)
cblo:   .byte $ff, $ff                  ; page row whose colours each bitmap's row 0 has
cbhi:   .byte $ff, $ff
cx:     .byte 0
call:   .byte 0

front:  .byte 0                         ; bitmap shown (0: A, 1: B)
base:   .word 0                         ; page line in its row 0
fs:     .byte 7                         ; fine scroll s
btag:   .word $ffff                     ; base the back holds ($ffff: none yet, or changing)
dir:    .byte 1                         ; last direction: 1 down, $ff up
quit:   .byte 0
iv:     .word 0                         ; IRQ: v
it:     .word 0                         ; IRQ: base wanted
pb:     .word 0                         ; main: base being prepared
pdir:   .byte 0
pfront: .byte 0
rr:     .byte 0                         ; render: row
li:     .byte 0                         ; render: line
ln:     .byte 0                         ; render: lines left

        .include "v2t.inc"
