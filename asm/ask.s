; vic2orious "ask" demo: an image with a menu of topics beside it. The number keys pick a
; topic, its answer is drawn line by line with v2t_line while the image stays on
; screen; space returns to BASIC. Content comes from input/<name>.ask (see vic2/ask.py).
; Assembled with AUTO=n (build --verify) it picks topic n by itself and then keeps
; drawing an invisible (black on black) line at the bottom, so the IRQ hits text code.

        .include "ask.inc"              ; generated: layout, colours, strings, the image

.ifndef AUTO
AUTO = 0
.endif
.ifndef FRAME
FRAME = 0
.endif
sel     = $06                           ; topic being answered ($ff: none)
mi      = $07
lp      = $fb                           ; 2 bytes: answer line

        .segment "LOADADDR"
        .word $0801
        .segment "EXEHDR"
        .word @next, 10
        .byte $9e, "2061", 0
@next:  .word 0

        .code
start:  jsr v2i_init
        lda #<ask_img
        ldy #>ask_img
        jsr v2i_show
.if FRAME
        lda #$10
        jsr v2i_frame
.endif
        jsr v2i_start                    ; everything below is drawn with the image showing
        lda #<ASK_X
        sta v2t_x
        lda #>ASK_X
        sta v2t_x+1
        lda #ASK_W
        sta v2t_cols
.if ASK_HAS_TITLE
        lda #ASK_TITLE_Y
        sta v2t_y
        lda #C_TITLE
        sta v2t_color
        lda #<ask_title
        ldy #>ask_title
        jsr v2t_line
.endif
.if AUTO = 0
        lda #ASK_FOOT_Y
        sta v2t_y
        lda #C_FOOT
        sta v2t_color
        lda #<ask_foot
        ldy #>ask_foot
        jsr v2t_line
.endif
        lda #$ff
        sta sel
        jsr menu
        lda #0                          ; the introduction
        jsr answer

.if AUTO
        lda v2i_ticks                    ; wait half a second, then pick topic AUTO
        clc
        adc #25
:       cmp v2i_ticks
        bne :-
        ldx #AUTO - 1
        jsr pick
stress: lda #ASK_FOOT_Y
        sta v2t_y
        lda #0                          ; black on black
        sta v2t_color
        lda #<ask_stress
        ldy #>ask_stress
        jsr v2t_line
        lda #<ask_stress
        ldy #>ask_stress
        jsr v2t_measure
        jmp stress
.else
main:   jsr scan
        bcs main
        cpx sel
        beq :+
        jsr pick
:       lda #0                          ; wait until no key is down
        sta $dc00
:       lda $dc01
        cmp #$ff
        bne :-
        jmp main
.endif

pick:   stx sel                         ; answer topic X
        jsr menu
        lda sel
        clc
        adc #1
        ; fall through

answer: tax                             ; clear the answer area, draw answer A line by line
        lda ask_ans_lo,x
        sta lp
        lda ask_ans_hi,x
        sta lp+1
        lda #ASK_COL
        sta v2t_col
        lda #ASK_ANS_ROW
        sta v2t_row
        lda #ASK_W
        sta v2t_cols
        lda #ASK_ANS_ROWS
        sta v2t_rows
        lda #0
        jsr v2t_clear
        lda #ASK_ANS_Y
        sta v2t_y
        lda #ASK_LEAD
        sta v2t_lead
@line:  ldy #0                          ; colour, screen codes, 0; $ff ends the answer
        lda (lp),y
        cmp #$ff
        beq @done
        sta v2t_color
        inc lp
        bne :+
        inc lp+1
:       lda lp
        ldy lp+1
        jsr v2t_line
        ldy #0                          ; lp = after the 0
:       lda (lp),y
        beq :+
        iny
        bne :-
:       iny
        tya
        clc
        adc lp
        sta lp
        bcc :+
        inc lp+1
:       lda v2i_ticks                    ; a little pause between lines
        clc
        adc #2
:       cmp v2i_ticks
        bne :-
        jmp @line
@done:  rts

menu:   lda #ASK_MENU_Y                 ; one line per topic, the one in sel highlighted
        sta v2t_y
        lda #0
        sta v2t_lead
        ldx #0
@m:     stx mi
        lda #C_BODY
        cpx sel
        bne :+
        lda #C_HILITE
:       sta v2t_color
        lda ask_lbl_lo,x
        ldy ask_lbl_hi,x
        jsr v2t_line
        ldx mi
        inx
        cpx #ASK_N
        bne @m
        rts

; X = index of the topic whose key is down (C=0), C=1 if none; space leaves to BASIC
scan:   ldx #ASK_N - 1
@k:     ldy ask_key,x                   ; digit 1-9
        lda key_col-1,y
        sta $dc00
        lda $dc01
        and key_row-1,y
        beq @hit
        dex
        bpl @k
        lda #$7f                        ; space: column 7, row 4
        sta $dc00
        lda $dc01
        and #$10
        beq @quit
        sec
        rts
@hit:   clc
        rts
@quit:  jsr v2i_exit
        jmp ($a002)                     ; BASIC warm start

; keyboard matrix position of the digits 1-9: CIA1 port A value, port B bit
key_col: .byte $7f, $7f, $fd, $fd, $fb, $fb, $f7, $f7, $ef
key_row: .byte $01, $08, $01, $08, $01, $08, $01, $08, $01

        .include "v2i.inc"
        .include "v2t.inc"
