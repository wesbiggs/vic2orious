; v2t demo: text on a hires bitmap without v2i. The KERNAL stays on; the bitmap is in VIC
; bank 1 ($6000, colours at $4400). Draws a centred title (v2t_measure + v2t_line), a .v2t
; story (the first one built, else a sample text) at a pixel position that is not cell
; aligned (cut off at the bottom if it is long), and a right-aligned footer, then waits for
; a key and returns to BASIC.

V2T_BITMAP = $6000
V2T_SCREEN = $4400

        .include "v2tdemo.inc"          ; generated: demo_txt, demo_title, demo_foot

GETIN   = $ffe4
TXT_X   = 16                            ; where the story goes (pixels)
TXT_Y   = 22 + V2T_FONT_H                ; below the title
FOOT_Y  = 192 - V2T_FONT_H

        .segment "LOADADDR"
        .word $0801
        .segment "EXEHDR"
        .word @next, 10
        .byte $9e, "2061", 0
@next:  .word 0

        .code
start:  lda #0
        sta $d020
        lda #0                          ; whole screen: blank, light grey on black
        sta v2t_col
        sta v2t_row
        lda #40
        sta v2t_cols
        lda #25
        sta v2t_rows
        lda #$f0
        jsr v2t_clear
        lda $dd02                       ; VIC bank 1, screen +$0400, bitmap +$2000
        ora #$03
        sta $dd02
        lda $dd00
        and #$fc
        ora #$02
        sta $dd00
        lda #$18
        sta $d018
        lda #$3b                        ; hires bitmap mode on
        sta $d011

        lda #8                          ; title, centred, white
        sta v2t_y
        lda #$10
        sta v2t_color
        lda #<demo_title
        ldy #>demo_title
        jsr centre
        lda #<demo_title
        ldy #>demo_title
        jsr v2t_line

        lda #<TXT_X                     ; the story
        sta v2t_x
        lda #>TXT_X
        sta v2t_x+1
        lda #TXT_Y
        sta v2t_y
        lda #2
        sta v2t_lead
        lda #<demo_txt
        ldy #>demo_txt
        jsr v2t_draw_at

        lda #FOOT_Y                     ; footer, bottom right, dark grey
        sta v2t_y
        lda #$b0
        sta v2t_color
        lda #<demo_foot
        ldy #>demo_foot
        jsr v2t_measure                 ; v2t_x = 312 - width
        sta v2t_x
        stx v2t_x+1
        sec
        lda #<312
        sbc v2t_x
        sta v2t_x
        lda #>312
        sbc v2t_x+1
        sta v2t_x+1
        lda #40                         ; to the right edge
        sta v2t_cols
        lda #<demo_foot
        ldy #>demo_foot
        jsr v2t_line

:       jsr GETIN                       ; wait for a key
        beq :-
        lda $dd00                       ; back to the text screen
        ora #$03
        sta $dd00
        lda #$15
        sta $d018
        lda #$1b
        sta $d011
        lda #14
        sta $d020
        rts

centre: jsr v2t_measure                 ; v2t_x = (320 - width of the text at A/Y) / 2,
        sta v2t_x                       ; 0 if wider than the screen
        stx v2t_x+1
        sec
        lda #<320
        sbc v2t_x
        sta v2t_x
        lda #>320
        sbc v2t_x+1
        bcs :+
        lda #0
        sta v2t_x
:       lsr
        sta v2t_x+1
        ror v2t_x
        lda #40                         ; and the line spans the whole width
        sta v2t_cols
        rts

        .include "v2t.inc"
