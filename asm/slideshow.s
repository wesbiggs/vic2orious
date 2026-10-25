; vic2orious slideshow: .v2i images (hires bitmap + per-line multiplexed hires sprites),
; embedded in the program. Space advances to the next image; otherwise images change
; every AUTO_FRAMES frames.

        .include "images.inc"           ; generated: IMAGE_COUNT, AUTO_FRAMES, img/txt tables, data

.ifndef FRAME
FRAME = 0                               ; 1: frame the images (build -b)
.endif
FRAME_COL = $10                         ; frame cells: white on black
frame   = $06
cur     = $07
req     = $0a
keyprev = $0b

        .segment "LOADADDR"
        .word $0801
        .segment "EXEHDR"
        .word @next, 10
        .byte $9e, "2061", 0
@next:  .word 0

        .code
start:  jsr v2i_init
        lda #<hook
        sta v2i_hook
        lda #>hook
        sta v2i_hook+1
        lda #0
        sta cur
        sta keyprev
        jsr select
        jsr v2i_start
main:   lda req
        beq main
        lda #0
        sta req
        ldx cur
        inx
        cpx #IMAGE_COUNT
        bcc :+
        ldx #0
:       stx cur
        jsr v2i_stop
        jsr select
        jsr v2i_start
        jmp main

select: ldx cur                         ; show image #cur and its text, if it has any
        lda img_lo,x
        ldy img_hi,x
        jsr v2i_show
.if FRAME
        lda #FRAME_COL
        jsr v2i_frame
.endif
        ldx cur
        ldy txt_hi,x
        beq :+
        lda txt_lo,x
        jsr v2t_draw
:       rts

hook:
        inc frame
        lda frame
        cmp #AUTO_FRAMES
        bcc :+
        lda #0
        sta frame
        lda #1
        sta req
:       lda #$7f                        ; keyboard row 7: space = bit 4
        sta $dc00
        lda $dc01
        and #$10
        tax
        eor #$10
        and keyprev                     ; pressed now (0) and released before (1)
        beq :+
        lda #1
        sta req
        lda #0
        sta frame
:       stx keyprev
        rts

        .include "v2i.inc"
        .include "v2t.inc"
