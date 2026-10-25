; vic2orious slideshow: .v2i images (hires bitmap + per-line multiplexed hires sprites),
; embedded in the program. Space advances to the next image; otherwise images change
; every AUTO_FRAMES frames (0: only on space).

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
        bcs fail
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
        bcs fail
        jsr v2i_start
        jmp main

select: ldx cur                         ; show image #cur and its text, if it has any;
        lda img_lo,x                    ; C=1, A = error: not shown
        ldy img_hi,x
        jsr v2i_show
        bcs @r
.if FRAME
        lda #FRAME_COL
        jsr v2i_frame
.endif
        ldx cur
        ldy txt_hi,x
        beq :+
        lda txt_lo,x
        jsr v2t_draw
:       clc
@r:     rts

hook:
.if AUTO_FRAMES
        inc frame
        lda frame
        cmp #AUTO_FRAMES
        bcc :+
        lda #0
        sta frame
        lda #1
        sta req
:
.endif
        lda #$7f                        ; keyboard row 7: space = bit 4
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

fail:   pha                             ; v2i_show failed: say why, back to BASIC
        jsr v2i_exit
        pla
        jsr v2i_errmsg
        sta $fb
        sty $fc
        ldy #0
:       lda ($fb),y
        beq :+
        jsr $ffd2                       ; CHROUT
        iny
        bne :-
:       lda #13
        jsr $ffd2
        jmp ($a002)                     ; BASIC warm start

        .include "v2i.inc"
        .include "v2t.inc"
