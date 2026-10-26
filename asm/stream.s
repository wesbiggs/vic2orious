; v2t stream demo: text arrives as a byte stream (here from stm_data, STM_RATE bytes a
; frame, 0: all at once) and the C64 lays it out itself: word wrap by pixel width into a
; ring of lines, each word drawn as soon as it is complete, and the page scrolls smoothly
; (one pixel per frame, downwards) whenever the newest line reaches the bottom. Space
; returns to BASIC.
;
; Stream: ASCII codes 33-127 (and 128-255, drawn as code & 127) make words; line feed (10)
; is a space, two in a row end a paragraph (a blank line before the next one); other codes
; up to 32 are spaces. A paragraph whose first word is "#" is a title (the "#" is not
; shown). Words are split after WMAX characters, and a line ends before it would pass
; STM_PX pixels (less the font's hang, as the build wraps) or LMAX characters.
;
; Lines: LN slots (text address, page y, colour), line numbers head (next) and tail
; (oldest live); texts in a byte ring TXT0-TXT1, each line contiguous and 0-terminated
; (a new line gets LMAX + 1 bytes or starts again at TXT0). Lines above the shown bitmap
; are dropped; the stream waits while there is no room for another line.
;
; Display as in scroll.s, downwards only: bitmaps A and B take turns, bb holds the base
; (page line of row 0) each one shows ($ffff: none). The raster IRQ scrolls while
; v < vt (8 pixels below the newest line at the bottom) and swaps when the back holds
; base + 8. The main loop prepares the back (row colours, 24 rows copied, row 24 drawn:
; every line that touches it, found by walking the ring from tail), and in between reads
; the stream; a finished word is ORed into each bitmap that shows its line. The stream is
; read only while the back is ready, so when time is short the stream waits, not the
; scroll. Assembled with STALLS=1 (build --verify), the border shows how many frames the
; scroll had to wait anyway (up to 15).

        .include "stream.inc"           ; generated: the stream and the layout constants

BMP_A   = $6000
SCR_A   = $4000
BMP_B   = $a000
SCR_B   = $8000
VOFF    = 4                             ; v2t draws 4 rows lower, into a bitmap 4 rows early
IRQ_LN  = 250
LN      = 64                            ; line slots (a power of 2, at most 128)
TXT0    = $4400                         ; text ring: after screen A, before the rows
TXT1    = $5b00                         ; v2t never writes ahead of bitmap A

p       = $fb                           ; 2 bytes each
q       = $fd
s       = $57                           ; the stream (BASIC's float scratch)
w       = $59

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
        lda #1                          ; lines are ORed in
        sta v2t_over
        lda #<BMP_A                     ; both bitmaps clear, both screens STM_BODY
        ldy #>BMP_A
        jsr setp
        ldx #32
        lda #0
        jsr fill
        lda #<BMP_B
        ldy #>BMP_B
        jsr setp
        ldx #32
        lda #0
        jsr fill
        lda #<SCR_A
        ldy #>SCR_A
        jsr setp
        ldx #4
        lda #STM_BODY
        jsr fill
        lda #<SCR_B
        ldy #>SCR_B
        jsr setp
        ldx #4
        lda #STM_BODY
        jsr fill
        lda #<space
        ldy #>space
        jsr v2t_measure
        sta spw
        lda #<stm_data
        sta s
        lda #>stm_data
        sta s+1
        lda #<TXT0
        sta tnext
        lda #>TXT0
        sta tnext+1

        lda #$7f                        ; IRQ: raster line IRQ_LN only
        sta $dc0d
        lda $dc0d
        lda #<irq
        sta $0314
        lda #>irq
        sta $0315
        lda #IRQ_LN
        sta $d012
        lda #$37                        ; bitmap, 24 rows, s = 7
        sta $d011
        lda #$08
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

; keep the back prepared (one row on), ahead of the scroll; else read the stream
main:   lda quit
        beq :+
        jmp exit
:       jsr freelines
        ldx front                       ; pb = the front's base + 8
        stx pf
        clc
        lda bblo,x
        adc #8
        sta pb
        lda bbhi,x
        adc #0
        sta pb+1
        txa
        eor #1
        tax
        lda bblo,x
        cmp pb
        bne @prep
        lda bbhi,x
        cmp pb+1
        beq @in                         ; the back holds it
@prep:  jsr prepare
        jmp main
@in:    jsr input
        jmp main

; ---- display

; the back (1 - pf) for base pb: row colours, rows 1-24 of the front to 0-23, row 24
prepare:
        lda pf
        eor #1
        tax
        stx pk
        sei                             ; no swap to it until it is done
        lda #$ff
        sta bblo,x
        sta bbhi,x
        cli
        ldx pf                          ; colours: p = front row 1, q = back row 0 (col 1)
        clc
        lda scr0lo,x
        adc #41
        sta p
        lda scr0hi,x
        adc #0
        sta p+1
        ldx pk
        clc
        lda scr0lo,x
        adc #1
        sta q
        lda scr0hi,x
        adc #0
        sta q+1
        ldx #24
@row:   ldy #0                          ; a row has one colour (columns 1-38): set it
        lda (p),y                       ; where it differs
        cmp (q),y
        beq @next
        ldy #37
:       sta (q),y
        dey
        bpl :-
@next:  clc
        lda p
        adc #40
        sta p
        bcc :+
        inc p+1
:       clc
        lda q
        adc #40
        sta q
        bcc :+
        inc q+1
:       dex
        bne @row
        lda pf
        bne :+
        jsr copy_ab
        jmp :++
:       jsr copy_ba
:       ldx pk
        jsr render
        sei
        ldx pk
        lda pb
        sta bblo,x
        lda pb+1
        sta bbhi,x
        cli
        rts

; row 24 of bitmap X for base pb: cleared, colour STM_BODY, then the lines touching it
render: stx dbuf
        clc                             ; clear: p = row 24, q = p + 160
        lda bmp0lo,x
        sta p
        adc #160
        sta q
        lda bmp0hi,x
        clc
        adc #>(24 * 320)
        sta p+1
        adc #0
        sta q+1
        lda #0
        ldy #160
:       dey
        sta (p),y
        sta (q),y
        bne :-
        clc                             ; colour columns 1-38
        lda scr0lo,x
        adc #<(24 * 40 + 1)
        sta p
        lda scr0hi,x
        adc #>(24 * 40 + 1)
        sta p+1
        lda #STM_BODY
        ldy #37
:       sta (p),y
        dey
        bpl :-
        lda #24 + VOFF                  ; clipped to it
        sta v2t_rtop
        lda #25 + VOFF
        sta v2t_rbot
        clc                             ; y0 = its page line
        lda pb
        sta dbase
        adc #192
        sta y0
        lda pb+1
        sta dbase+1
        adc #0
        sta y0+1
        lda #<STM_X
        sta dx
        lda #>STM_X
        sta dx+1
        lda tail
        sta li
@ln:    lda li
        cmp head
        beq @done
        and #LN - 1
        tax
        stx dsl
        sec                             ; d = line's y - y0
        lda sl_ylo,x
        sbc y0
        sta t
        lda sl_yhi,x
        sbc y0+1
        bmi @neg
        bne @done                       ; d >= 8: this and all later lines are below
        lda t
        cmp #8
        bcs @done
        bcc @draw
@neg:   cmp #$ff                        ; d < 0: touches if d + H > 0
        bne @nx
        clc
        lda t
        adc #V2T_FONT_H
        bcc @nx
        beq @nx
@draw:  lda sl_tlo,x
        sta dtp
        lda sl_thi,x
        sta dtp+1
        jsr vdraw
@nx:    inc li
        jmp @ln
@done:  rts

; draw text dtp of line slot dsl from x = dx into bitmap dbuf showing base dbase, if the
; line is on it (clip window set by the caller)
vdraw:  ldx dsl
        sec
        lda sl_ylo,x                    ; v2t_y = y - base + 8 * VOFF, if 0..199 + 8 * VOFF
        sbc dbase
        sta t
        lda sl_yhi,x
        sbc dbase+1
        sta t+1
        clc
        lda t
        adc #8 * VOFF
        sta v2t_y
        lda t+1
        adc #0
        bne @out
        lda v2t_y
        cmp #200 + 8 * VOFF
        bcs @out
        lda sl_clr,x
        sta v2t_color
        lda dx
        sta v2t_x
        lda dx+1
        sta v2t_x+1
        lsr                             ; cells from x / 8 to column 38
        lda dx
        ror
        lsr
        lsr
        sta t
        sec
        lda #39
        sbc t
        sta v2t_cols
        ldx dbuf
        lda bmplo,x
        sta v2t_bitmap
        lda bmphi,x
        sta v2t_bitmap+1
        lda scrlo,x
        sta v2t_screen
        lda scrhi,x
        sta v2t_screen+1
        lda dtp
        ldy dtp+1
        jmp v2t_line
@out:   rts

; drop the lines above the front's base (not the line being filled)
freelines:
        ldx front
        lda bblo,x
        sta fb
        lda bbhi,x
        sta fb+1
@l:     lda tail
        cmp head
        beq @rts
        lda copen
        beq :+
        ldx head
        dex
        cpx tail
        beq @rts
:       lda tail
        and #LN - 1
        tax
        clc                             ; gone if base - (y + H) >= 0
        lda sl_ylo,x
        adc #V2T_FONT_H
        sta t
        lda sl_yhi,x
        adc #0
        sta t+1
        sec
        lda fb
        sbc t
        lda fb+1
        sbc t+1
        bmi @rts
        inc tail
        jmp @l
@rts:   rts

; ---- the stream

; one byte of the stream, if there is room for another line
input:  lda eof
        bne @rts
        jsr room
        bcs @rts                        ; full: wait for the scroll
        jsr getc
        bcc @chr
        lda s                           ; nothing now: at the end?
        cmp #<stm_end
        bne @rts
        lda s+1
        cmp #>stm_end
        bne @rts
        inc eof
        jmp endpara
@chr:   cmp #10
        bne @nolf
        jsr endword
        inc nl
        lda nl
        cmp #2
        bne @rts
        jmp endpara
@nolf:  cmp #33
        bcs @wch
        jsr endword
        lda #0
        sta nl
@rts:   rts
@wch:   pha
        lda #0
        sta nl
        lda wlen
        cmp #WMAX
        bne :+
        jsr endword
:       pla
        ldx wlen
        sta wb,x
        inc wlen
        rts

; A = the next byte (C=0), C=1: none yet or the end
getc:   lda s
        cmp #<stm_end
        bne :+
        lda s+1
        cmp #>stm_end
        beq @none
:
.if STM_RATE
        sei                             ; one of the bytes received so far
        lda avail
        ora avail+1
        bne :+
        cli
        sec
        rts
:       lda avail
        bne :+
        dec avail+1
:       dec avail
        cli
.endif
        ldy #0
        lda (s),y
        inc s
        bne :+
        inc s+1
:       clc
        rts
@none:  sec
        rts

endword:
        lda wlen
        beq @rts
        tax
        lda #0
        sta wb,x
        lda #<wb
        ldy #>wb
        jsr v2t_measure
        sta ww
        stx ww+1
        jsr place
        lda #0
        sta wlen
@rts:   rts

endpara:
        jsr endword
        lda #0
        sta copen
        lda had
        beq :+
        sta anyp
:       lda #0
        sta had
        sta title
        rts

; the word wb (wlen characters, ww pixels): onto the line being filled, or a new one
place:  lda had
        bne @cont
        lda title                       ; a paragraph's first word "#": a title
        bne @first
        lda wlen
        cmp #1
        bne @first
        lda wb
        cmp #'#'
        bne @first
        inc title
        rts
@first: lda #1
        sta had
        lda anyp                        ; a blank line between paragraphs
        beq :+
        clc
        lda ny
        adc #STM_PITCH
        sta ny
        bcc :+
        inc ny+1
:       lda #0
        sta copen
@cont:  lda copen
        beq @new
        clc                             ; t = width with " " and the word
        lda curw
        adc spw
        sta t
        lda curw+1
        adc #0
        sta t+1
        clc
        lda t
        adc ww
        sta t
        lda t+1
        adc ww+1
        sta t+1
        lda #<(STM_PX + V2T_FONT_HANG)  ; fits if t - hang <= STM_PX
        cmp t
        lda #>(STM_PX + V2T_FONT_HANG)
        sbc t+1
        bcc @new
        lda clen                        ; and clen + 1 + wlen <= LMAX
        sec
        adc wlen
        bcs @new
        cmp #LMAX + 1
        bcs @new
        jmp append
@new:   jmp newline

newline:
        lda head
        and #LN - 1
        tax
        stx csl
        lda ns                          ; text at ns (room set it)
        sta sl_tlo,x
        sta w
        sta dtp
        lda ns+1
        sta sl_thi,x
        sta w+1
        sta dtp+1
        lda ny
        sta sl_ylo,x
        lda ny+1
        sta sl_yhi,x
        lda #STM_BODY
        ldy title
        beq :+
        lda #STM_TITLE
:       sta sl_clr,x
        clc
        lda ny
        adc #STM_PITCH
        sta ny
        bcc :+
        inc ny+1
:       inc head
        lda #1
        sta copen
        ldy #0
:       lda wb,y
        sta (w),y
        iny
        cpy wlen
        bne :-
        lda #0
        sta (w),y
        sec                             ; tnext = after its 0
        lda w
        adc wlen
        sta tnext
        lda w+1
        adc #0
        sta tnext+1
        lda wlen
        sta clen
        lda ww
        sta curw
        lda ww+1
        sta curw+1
        sei                             ; scroll until it is 8 pixels above the bottom
        clc
        lda sl_ylo,x
        adc #<(V2T_FONT_H + 8 - 192)
        sta vt
        lda sl_yhi,x
        adc #>(V2T_FONT_H + 8 - 192)
        sta vt+1
        cli
        lda #<STM_X
        sta dx
        lda #>STM_X
        sta dx+1
        jmp drawword

append: sec                             ; " " and the word over the line's 0
        lda tnext
        sbc #1
        sta w
        lda tnext+1
        sbc #0
        sta w+1
        ldy #0
        lda #' '
        sta (w),y
        ldx #0
:       lda wb,x
        iny
        sta (w),y
        inx
        cpx wlen
        bne :-
        iny
        lda #0
        sta (w),y
        clc                             ; x = STM_X + curw + spw; curw = that + ww
        lda curw
        adc spw
        sta t
        lda curw+1
        adc #0
        sta t+1
        clc
        lda t
        adc #<STM_X
        sta dx
        lda t+1
        adc #>STM_X
        sta dx+1
        clc
        lda t
        adc ww
        sta curw
        lda t+1
        adc ww+1
        sta curw+1
        lda clen                        ; clen, tnext += 1 + wlen
        sec
        adc wlen
        sta clen
        lda tnext
        sec
        adc wlen
        sta tnext
        bcc :+
        inc tnext+1
:       clc                             ; the word starts after the " "
        lda w
        adc #1
        sta dtp
        lda w+1
        adc #0
        sta dtp+1
        ldx csl
        ; fall through

; draw the word (dtp, from dx) of line slot X into the front, and into the back if it
; holds the front's base + 8
drawword:
        stx dsl
        lda #VOFF
        sta v2t_rtop
        lda #VOFF + 25
        sta v2t_rbot
        lda front
        sta df
        tay
        eor #1
        tax
        clc
        lda bblo,y
        adc #8
        sta t
        lda bbhi,y
        adc #0
        cmp bbhi,x
        bne @front
        lda t
        cmp bblo,x
        bne @front
        stx dbuf
        lda bblo,x
        sta dbase
        lda bbhi,x
        sta dbase+1
        jsr vdraw
@front: ldx df
        stx dbuf
        lda bblo,x
        sta dbase
        lda bbhi,x
        sta dbase+1
        jmp vdraw

; C=0 if there is a free slot and LMAX + 1 free bytes for another line, at ns
room:   lda head
        sec
        sbc tail
        cmp #LN
        bcs @full
        clc                             ; t = tnext + LMAX + 1
        lda tnext
        adc #LMAX + 1
        sta t
        lda tnext+1
        adc #0
        sta t+1
        lda #<TXT1
        cmp t
        lda #>TXT1
        sbc t+1
        bcc @wrap
        lda tnext
        sta ns
        lda tnext+1
        sta ns+1
        lda head
        cmp tail
        beq @ok
        jsr tailp                       ; free unless tnext <= tail's text < t
        lda tp
        cmp tnext
        lda tp+1
        sbc tnext+1
        bcc @ok
        lda tp
        cmp t
        lda tp+1
        sbc t+1
        bcs @ok
@full:  sec
        rts
@wrap:  lda #<TXT0                      ; no room before TXT1: start again at TXT0
        sta ns
        lda #>TXT0
        sta ns+1
        lda head
        cmp tail
        beq @ok
        jsr tailp                       ; free if the live text doesn't wrap and starts
        lda tp                          ; at TXT0 + LMAX + 1 or later
        cmp tnext
        lda tp+1
        sbc tnext+1
        bcs @full
        lda tp
        cmp #<(TXT0 + LMAX + 1)
        lda tp+1
        sbc #>(TXT0 + LMAX + 1)
        bcc @full
@ok:    clc
        rts

tailp:  lda tail                        ; tp = text of the oldest line
        and #LN - 1
        tax
        lda sl_tlo,x
        sta tp
        lda sl_thi,x
        sta tp+1
        rts

; ---- IRQ, machine

irq:    asl $d019
.if STM_RATE
        lda avail+1                     ; STM_RATE more bytes received
        cmp #$40
        bcs :+
        clc
        lda avail
        adc #STM_RATE
        sta avail
        bcc :+
        inc avail+1
:
.endif
        lda #$7f                        ; space: column 7, row 4
        sta $dc00
        lda $dc01
        and #$10
        bne :+
        inc quit
:       ldx front                       ; scroll while v < vt
        sec
        lda #7
        sbc fs
        clc
        adc bblo,x
        sta iv
        lda bbhi,x
        adc #0
        sta iv+1
        sec
        lda iv
        sbc vt
        lda iv+1
        sbc vt+1
        bpl @set
        lda fs
        beq :+
        dec fs
        jmp @set
:       clc                             ; s = 0: swap if the back holds base + 8
        lda bblo,x
        adc #8
        sta it
        lda bbhi,x
        adc #0
        sta it+1
        txa
        eor #1
        tay
        lda bblo,y
        cmp it
        bne @stall
        lda bbhi,y
        cmp it+1
        bne @stall
        sty front
        lda #7
        sta fs
        bne @set
@stall:
.ifdef STALLS
        lda stalls                      ; frames the back wasn't ready, in the border
        cmp #15                         ; (written only then: a colour register write
        bcs @set                        ; shows as a dot on 85xx VIC-IIs)
        inc stalls
        lda stalls
        sta $d020
.endif
@set:   lda fs
        ora #$30
        sta $d011
        ldx front
        jsr bank
        jmp $ea81

bank:   lda $dd00                       ; VIC bank of bitmap X
        and #$fc
        ora banks,x
        sta $dd00
        rts

setp:   sta p                           ; p = A/Y
        sty p+1
        rts
fill:   ldy #0                          ; X pages from p = A
:       sta (p),y
        iny
        bne :-
        inc p+1
        dex
        bne :-
        rts

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
        jmp ($a002)

; rows 1-24 of one bitmap to rows 0-23 of the other (7680 bytes)
.macro rows src, dst
        ldx #0
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
copy_ab: rows BMP_A + 320, BMP_B
copy_ba: rows BMP_B + 320, BMP_A

        .data
bmplo:  .byte <(BMP_A - VOFF * 320), <(BMP_B - VOFF * 320)
bmphi:  .byte >(BMP_A - VOFF * 320), >(BMP_B - VOFF * 320)
scrlo:  .byte <(SCR_A - VOFF * 40), <(SCR_B - VOFF * 40)
scrhi:  .byte >(SCR_A - VOFF * 40), >(SCR_B - VOFF * 40)
bmp0lo: .byte <BMP_A, <BMP_B
bmp0hi: .byte >BMP_A, >BMP_B
scr0lo: .byte <SCR_A, <SCR_B
scr0hi: .byte >SCR_A, >SCR_B
banks:  .byte $02, $01
space:  .byte " ", 0

bblo:   .byte 0, $ff                    ; base each bitmap holds ($ffff: none)
bbhi:   .byte 0, $ff
front:  .byte 0
fs:     .byte 7
vt:     .word $ff00                     ; scroll target (signed: none yet)
quit:   .byte 0
stalls: .byte 0                         ; STALLS: count (to 15) in the border
avail:  .word 0                         ; stream bytes received, not read yet
iv:     .word 0                         ; IRQ
it:     .word 0
pf:     .byte 0                         ; main: front, back, base being prepared
pk:     .byte 0
pb:     .word 0
y0:     .word 0                         ; render
li:     .byte 0
t:      .word 0
fb:     .word 0
dbuf:   .byte 0                         ; vdraw: bitmap, its base, line slot, text, x
dbase:  .word 0
dsl:    .byte 0
dtp:    .word 0
dx:     .word 0
df:     .byte 0

head:   .byte 0                         ; lines: next number, oldest live one
tail:   .byte 0
copen:  .byte 0                         ; a line is being filled (head - 1, slot csl)
csl:    .byte 0
curw:   .word 0                         ; its width in pixels, length in characters
clen:   .byte 0
tnext:  .word 0                         ; text ring: where the next line goes
ns:     .word 0                         ; room: where it goes now
tp:     .word 0
ny:     .word STM_TOP                   ; page y of the next line
had:    .byte 0                         ; the paragraph has words, is a title; a paragraph
title:  .byte 0                         ; with words came before
anyp:   .byte 0
nl:     .byte 0                         ; line feeds in a row
eof:    .byte 0
spw:    .byte 0                         ; width of " "
wlen:   .byte 0                         ; the word being read, its width
ww:     .word 0
wb:     .res WMAX + 1
sl_tlo: .res LN                         ; line slots
sl_thi: .res LN
sl_ylo: .res LN
sl_yhi: .res LN
sl_clr: .res LN

        .include "v2t.inc"
