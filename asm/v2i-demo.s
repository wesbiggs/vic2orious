; v2i demo: the smallest complete v2i program. Shows one image (the first one built),
; framed when assembled with FRAME=1, and returns to BASIC when space is pressed.
; Assembled with DUAL=1 it holds the image twice, made for PAL and for NTSC, and shows
; the one that suits the machine.

        .include "v2idemo.inc"          ; generated: demo_img (DUAL: and demo_img_n, NTSC)

.ifndef FRAME
FRAME = 0
.endif
.ifndef DUAL
DUAL = 0
.endif

        .segment "LOADADDR"
        .word $0801
        .segment "EXEHDR"
        .word @next, 10
        .byte $9e, "2061", 0
@next:  .word 0

        .code
start:  jsr v2i_init
        lda #<demo_img
        ldy #>demo_img
.if DUAL
        ldx v2i_system                  ; set by v2i_init
        cpx #V2I_NTSC
        bne :+
        lda #<demo_img_n
        ldy #>demo_img_n
:
.endif
        jsr v2i_show
        bcs fail                        ; not for this machine (PAL/NTSC)
.if FRAME
        lda #$10                        ; white on black
        jsr v2i_frame
.endif
        jsr v2i_start
        lda #$7f                        ; keyboard column 7: space = row bit 4
        sta $dc00
@up:    lda $dc01                       ; wait for release, then press
        and #$10
        beq @up
@down:  lda $dc01
        and #$10
        bne @down
        jsr v2i_exit
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
