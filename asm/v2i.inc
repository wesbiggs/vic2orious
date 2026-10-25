; v2i: displays a .v2i image (hires bitmap + per-line multiplexed sprites, docs/v2i-format.md)
; on a C64. ca65 source: .include it in the host program. API in docs/v2i-lib.md; in short
; (A/Y = address: A low, Y high):
;
;   v2i_init       take over the machine (ROMs and CIA interrupts off, VIC bank 3, own
;                  IRQ/NMI vectors); saves the VIC and CIA2 bank registers for v2i_exit
;   v2i_show       A/Y = .v2i: unpack it into VIC bank 3 (stopped only). C=1: not a .v2i
;   v2i_frame      A = colour: frame around the image (needs the ring of cells around it)
;   v2i_start      raster IRQ on: the image is displayed, v2i_hook is called every frame
;   v2i_stop       raster IRQ off, sprites off, screen blank
;   v2i_exit       v2i_stop, restore the registers saved by v2i_init, KERNAL back on, CLI
;
; The kernel and the IRQ touch only $02, the first 3 bytes at V2I_ZP and VIC registers.
; Memory: VIC bank 3 ($c000-$ffff) is the screen: $c000 screen, $c3f8 sprite pointers,
; $c400.. sprite blocks, $e000 bitmap; v2i_show clears $c000-$feff. Zero page: $02 (the
; kernels' sync code) and V2I_ZP_SIZE bytes from V2I_ZP (default $10).
; Text beside the image: v2t.inc with its defaults (bitmap $e000, screen $c000).

.ifndef V2I_ZP
V2I_ZP = $10
.endif

; .v2i header offsets
V2I_H_KLEN = 8
V2I_H_BLEN = 10
V2I_H_SLEN = 12
V2I_H_BDST = 16
V2I_H_SDST = 18
V2I_H_SIZE = 24

; zero page
v2i_save_a = V2I_ZP + 0                 ; IRQ register save (keep in zero page: the kernel
v2i_save_x = V2I_ZP + 1                 ; entry window depends on the prologue's timing)
v2i_save_y = V2I_ZP + 2
v2i_hdr    = V2I_ZP + 3                 ; 2 bytes each
v2i_ptr    = V2I_ZP + 5
v2i_src    = V2I_ZP + 7
v2i_dst    = V2I_ZP + 9
v2i_scr    = V2I_ZP + 11
V2I_ZP_SIZE = 13

; ---- take over the machine: ROMs out, CIA interrupts off, VIC bank 3, our vectors
v2i_init:
        sei
        lda $01
        sta v2i_save01
        lda #$35                        ; RAM at $a000/$e000, I/O visible
        sta $01
        ldx #$2e
:       lda $d000,x
        sta v2i_vic,x
        dex
        bpl :-
        lda $dd00
        sta v2i_savedd00
        lda $dd02
        sta v2i_savedd02
        lda #$7f
        sta $dc0d
        sta $dd0d
        lda $dc0d
        lda $dd0d
        lda #0
        sta $d01a
        sta $d015
        sta $d020
        sta $d021
        lda #$0b                        ; display off while setting up
        sta $d011
        lda #<v2i_irq
        sta $fffe
        lda #>v2i_irq
        sta $ffff
        lda #<v2i_nmi
        sta $fffa
        lda #>v2i_nmi
        sta $fffb
        lda $dd02
        ora #$03
        sta $dd02
        lda $dd00
        and #$fc                        ; VIC bank 3 ($c000-$ffff)
        sta $dd00
        lda #$ff
        sta $dc02                       ; CIA1 port A output (keyboard columns)
        lda #0
        sta $dc03
        rts

; ---- start/stop the raster interrupt that runs the kernel
v2i_start:
        lda #2
        sta $d012
        lda #$3b
        sta $d011
        lda #1
        sta $d019
        sta $d01a
        cli
        rts

v2i_stop:
        sei
        lda #0
        sta $d01a
        sta $d015
        lda #$0b
        sta $d011
        lda #1
        sta $d019
        rts

; ---- give the machine back: VIC registers and bank as v2i_init found them, ROMs and the
; KERNAL's CIA1 timer interrupt on
v2i_exit:
        jsr v2i_stop
        lda v2i_savedd02
        sta $dd02
        lda $dd00
        and #$fc
        sta v2i_ptr
        lda v2i_savedd00
        and #$03
        ora v2i_ptr
        sta $dd00
        ldx #$2e                        ; (writes to the read-only ones do nothing)
:       lda v2i_vic,x
        sta $d000,x
        dex
        bpl :-
        lda #$0f
        sta $d019
        lda v2i_save01
        sta $01
        lda #$81                        ; CIA1 timer A interrupt (KERNAL keyboard scan)
        sta $dc0d
        lda $dc0d
        cli
        rts

v2i_nmi:
        rti

; Entry timing matters only loosely: the kernel's sync phase absorbs a range of entry
; cycles, but keep this prologue as it is.
v2i_irq:
        sta v2i_save_a
        stx v2i_save_x
        sty v2i_save_y
        jsr v2i_kjump
        lda #1
        sta $d019
        inc v2i_ticks
        jsr v2i_hjump
        lda v2i_save_a
        ldx v2i_save_x
        ldy v2i_save_y
        rti
v2i_kjump:
        jmp (v2i_kvec)
v2i_hjump:
        jmp (v2i_hook)
v2i_rts:
        rts

; ---- unpack the image at A/Y into VIC bank 3 and point the IRQ at its kernel
v2i_show:
        sta v2i_hdr
        sty v2i_hdr+1
        ldy #3                          ; "V2I" + version
:       lda (v2i_hdr),y
        cmp v2i_magic,y
        bne @bad
        dey
        bpl :-
        ldy #4                          ; size and position
:       lda (v2i_hdr),y
        sta v2i_cols-4,y
        iny
        cpy #8
        bne :-
        lda v2i_row                     ; first raster line below the image
        clc
        adc v2i_rows
        asl
        asl
        asl
        adc #$33
        sta v2i_end
        lda #$34                        ; all RAM (sprites live partly under I/O)
        sta $01
        lda #$00                        ; clear $c000-$feff
        sta v2i_dst
        lda #$c0
        sta v2i_dst+1
        ldy #0
        tya
@clr:   sta (v2i_dst),y
        iny
        bne @clr
        inc v2i_dst+1
        ldx v2i_dst+1
        cpx #$ff
        bne @clr
        ldy #$3f                        ; and $ff00-$ff3f, the end of bitmap row 24
:       sta $ff00,y
        dey
        bpl :-
        clc                             ; ptr = start of kernel code
        lda v2i_hdr
        adc #V2I_H_SIZE
        sta v2i_ptr
        sta v2i_kvec
        lda v2i_hdr+1
        adc #0
        sta v2i_ptr+1
        sta v2i_kvec+1
        ldy #V2I_H_KLEN
        jsr v2i_advance
        ldy #V2I_H_BDST                 ; bitmap rows, decoded straight into place
        jsr v2i_unpack
        ldy #V2I_H_BLEN
        jsr v2i_advance
        ldy #V2I_H_SDST                 ; screen (colour) rows
        jsr v2i_unpack
        ldy #V2I_H_SLEN
        jsr v2i_advance
        lda #<$c400                     ; sprite blocks from pointer 16 on
        sta v2i_dst
        lda #>$c400
        sta v2i_dst+1
        jsr v2i_unpack_to_dst
        lda #$35
        sta $01
        clc
        rts
@bad:   sec
        rts

; ---- frame in the ring of cells around the image (rows fy0..fy1, columns fx0..fx1),
; rings white, white, black, white from the outside in, in cell colour A ($10: white on
; black); nothing if the ring does not fit on the screen
v2i_fno:
        rts
v2i_frame:
        sta v2i_fcol
        lda v2i_col                     ; fx0 = col0 - 1, fx1 = col0 + cols
        beq v2i_fno
        sta v2i_fx0
        dec v2i_fx0
        clc
        adc v2i_cols
        sta v2i_fx1
        cmp #40
        bcs v2i_fno
        lda v2i_row                     ; fy0 = row0 - 1, fy1 = row0 + rows
        beq v2i_fno
        sta v2i_fy0
        dec v2i_fy0
        clc
        adc v2i_rows
        sta v2i_fy1
        cmp #25
        bcs v2i_fno
        lda v2i_fx0                     ; top and bottom rows
        sta v2i_fx
@tb:    ldx #V2I_FP_T
        lda v2i_fx
        cmp v2i_fx0
        bne :+
        ldx #V2I_FP_TL
:       cmp v2i_fx1
        bne :+
        ldx #V2I_FP_TR
:       stx v2i_fpat
        lda v2i_fy0
        sta v2i_fy
        txa
        jsr v2i_fcell
        lda v2i_fy1
        sta v2i_fy
        lda v2i_fpat
        clc
        adc #V2I_FP_BL - V2I_FP_TL
        jsr v2i_fcell
        inc v2i_fx
        lda v2i_fx1
        cmp v2i_fx
        bcs @tb
        ldx v2i_fy0                     ; left and right columns
        inx
        stx v2i_fy
@lr:    lda v2i_fy
        cmp v2i_fy1
        bcs @done
        lda v2i_fx0
        sta v2i_fx
        lda #V2I_FP_L
        jsr v2i_fcell
        lda v2i_fx1
        sta v2i_fx
        lda #V2I_FP_R
        jsr v2i_fcell
        inc v2i_fy
        bne @lr
@done:  rts

v2i_fcell:                              ; cell (fx, fy) = frame pattern A, colour fcol
        pha
        ldx v2i_fy
        jsr v2i_rowaddr
        lda v2i_fx
        clc
        adc v2i_scr
        sta v2i_scr
        bcc :+
        inc v2i_scr+1
:       lda v2i_fcol
        ldy #0
        sta (v2i_scr),y
        lda v2i_fx                      ; dst += fx * 8
        asl
        asl
        asl
        bcc :+
        inc v2i_dst+1
:       clc
        adc v2i_dst
        sta v2i_dst
        bcc :+
        inc v2i_dst+1
:       pla
        tax
@cp:    lda v2i_frame_pat,x
        sta (v2i_dst),y
        inx
        iny
        cpy #8
        bne @cp
        rts

; frame cells, 8 bitmap bytes each (1 = foreground), the innermost ring next to the image
V2I_FP_TL = 0
V2I_FP_T  = 8
V2I_FP_TR = 16
V2I_FP_L  = 24
V2I_FP_R  = 32
V2I_FP_BL = 40
V2I_FP_B  = 48
V2I_FP_BR = 56
v2i_frame_pat:
        .byte $00, $00, $00, $00, $0f, $0f, $0c, $0d
        .byte $00, $00, $00, $00, $ff, $ff, $00, $ff
        .byte $00, $00, $00, $00, $f0, $f0, $30, $b0
        .byte $0d, $0d, $0d, $0d, $0d, $0d, $0d, $0d
        .byte $b0, $b0, $b0, $b0, $b0, $b0, $b0, $b0
        .byte $0d, $0c, $0f, $0f, $00, $00, $00, $00
        .byte $ff, $00, $ff, $ff, $00, $00, $00, $00
        .byte $b0, $30, $f0, $f0, $00, $00, $00, $00

; dst = $e000 + X * 320, scr = $c000 + X * 40 (bitmap and screen address of char row X)
v2i_rowaddr:
        lda #<$e000
        sta v2i_dst
        lda #>$e000
        sta v2i_dst+1
        lda #<$c000
        sta v2i_scr
        lda #>$c000
        sta v2i_scr+1
        cpx #0
        beq @done
@mul:   clc
        lda v2i_dst
        adc #<320
        sta v2i_dst
        lda v2i_dst+1
        adc #>320
        sta v2i_dst+1
        clc
        lda v2i_scr
        adc #40
        sta v2i_scr
        bcc :+
        inc v2i_scr+1
:       dex
        bne @mul
@done:  rts

v2i_advance:                            ; ptr += word at (hdr),y
        clc
        lda v2i_ptr
        adc (v2i_hdr),y
        sta v2i_ptr
        iny
        lda v2i_ptr+1
        adc (v2i_hdr),y
        sta v2i_ptr+1
        rts

v2i_unpack:                             ; dst = word at (hdr),y; decode (ptr) -> (dst)
        lda (v2i_hdr),y
        sta v2i_dst
        iny
        lda (v2i_hdr),y
        sta v2i_dst+1
v2i_unpack_to_dst:
        lda v2i_ptr
        sta v2i_src
        lda v2i_ptr+1
        sta v2i_src+1
        ; fall through

; zero-run-length decode (src) -> (dst): $00,n = n zero bytes, $00,$00 ends
v2i_unrle:
        ldy #0
@sp:    lda (v2i_src),y
        bne @lit
        jsr @next
        lda (v2i_src),y
        beq @done
        tax
        lda #0
@zr:    sta (v2i_dst),y
        inc v2i_dst
        bne :+
        inc v2i_dst+1
:       dex
        bne @zr
        jsr @next
        jmp @sp
@lit:   sta (v2i_dst),y
        inc v2i_dst
        bne :+
        inc v2i_dst+1
:       jsr @next
        jmp @sp
@next:  inc v2i_src
        bne @done
        inc v2i_src+1
@done:  rts

; ---- data and state

v2i_magic: .byte "V2I", 1
v2i_hook:  .word v2i_rts                ; called after the kernel every frame, may use A/X/Y
v2i_ticks: .byte 0                      ; incremented every frame

; image info, set by v2i_show
v2i_cols:  .byte 0                      ; size in cells
v2i_rows:  .byte 0
v2i_col:   .byte 0                      ; position in cells
v2i_row:   .byte 0
v2i_end:   .byte 0                      ; first raster line below the image (the kernel
                                        ; returns and v2i_hook runs about then)

; internal
v2i_kvec:  .word 0
v2i_save01: .byte 0
v2i_savedd00: .byte 0
v2i_savedd02: .byte 0
v2i_vic:   .res $2f
v2i_fx0:   .byte 0
v2i_fx1:   .byte 0
v2i_fy0:   .byte 0
v2i_fy1:   .byte 0
v2i_fx:    .byte 0
v2i_fy:    .byte 0
v2i_fpat:  .byte 0
v2i_fcol:  .byte 0
