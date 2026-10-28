; vic2orious viewer: loads a .v2i image from disk with the KERNAL and shows it.
; If a text file named like the image (first 12 characters + ".TXT") exists, it is drawn
; next to the image. Space returns to the file prompt; an empty file name exits to BASIC.
; Assembled with DUAL=1 (a disk with PAL and NTSC images) it first tries the name +
; "-p.v2i" or "-n.v2i", whichever suits the machine, then the name as typed; with the
; first, the text is name + "-p.txt" / "-n.txt" if that exists, else as above.

CHRIN   = $ffcf
CHROUT  = $ffd2
SETLFS  = $ffba
SETNAM  = $ffbd
LOAD    = $ffd5
GETIN   = $ffe4
LOADBUF = $2800                         ; images are loaded here (up to $97ff)
TXTBUF  = $9800                         ; text files are loaded here (up to $9fff, below the
                                        ; BASIC ROM, which is on when it is checked)

.ifndef FRAME
FRAME = 0                               ; 1: frame the images (build -b)
.endif
.ifndef DUAL
DUAL = 0
.endif
FRAME_COL = $10                         ; frame cells: white on black
namelen = $0c
hastext = $0a
vptr    = $fb                           ; 2 bytes

        .segment "LOADADDR"
        .word $0801
        .segment "EXEHDR"
        .word @next, 10
        .byte $9e, "2061", 0
@next:  .word 0

        .code
start:
prompt: lda #<msg_prompt
        ldy #>msg_prompt
        jsr print
        ldx #0                          ; read a line
@rd:    jsr CHRIN
        cmp #13
        beq @eol
        cpx #16
        bcs @rd
        sta name,x
        inx
        bne @rd
@eol:   stx namelen
        lda #13
        jsr CHROUT
        lda namelen
        bne @load
        jmp ($a002)                     ; BASIC warm start
@load:  lda #<msg_loading
        ldy #>msg_loading
        jsr print
.if DUAL
        lda #0
        sta dualname
        lda namelen                     ; name + "-P.V2I" / "-N.V2I", if that fits in 16
        cmp #11
        bcs @plain
        jsr v2i_detect
        ldy #0
:       lda name,y
        sta namebuf,y
        iny
        cpy namelen
        bne :-
        ldx #0
        lda v2i_system
        cmp #V2I_NTSC
        bne :+
        ldx #6
:       lda suffix,x
        sta namebuf,y
        iny
        inx
        cpx #6
        beq :+
        cpx #12
        bne :-
:       tya
        ldx #<namebuf
        ldy #>namebuf
        jsr SETNAM
        ldx #<LOADBUF
        ldy #>LOADBUF
        jsr loadfile
        bcs @plain
        inc dualname
        bcc @check
@plain:
.endif
        lda namelen
        ldx #<name
        ldy #>name
        jsr SETNAM
        ldx #<LOADBUF
        ldy #>LOADBUF
        jsr loadfile
        bcc @check
        lda #<msg_ioerr
        ldy #>msg_ioerr
        jsr print
        jmp prompt
@check: ldx #3                          ; "V2I" + version
@cm:    lda LOADBUF,x
        cmp magic,x
        bne @bad
        dex
        bpl @cm
        lda #0
        sta hastext
.if DUAL
        lda dualname                    ; loaded name + "-P.V2I": try name + "-P.TXT"
        beq @shared
        ldy namelen
        ldx #0
:       lda txtext+1,x
        sta namebuf+3,y
        iny
        inx
        cpx #3
        bne :-
        tya
        clc
        adc #3
        ldx #<namebuf
        ldy #>namebuf
        jsr SETNAM
        jsr loadtext
        lda hastext
        bne view
@shared:
.endif
        ldx namelen                     ; optional text: name[0..11] + ".TXT"
        cpx #12
        bcc :+
        ldx #12
:       ldy #0
:       lda txtext,y
        sta name,x
        inx
        iny
        cpy #4
        bne :-
        txa
        ldx #<name
        ldy #>name
        jsr SETNAM
        jsr loadtext
        jmp view
@bad:   lda #<msg_notv2i
        ldy #>msg_notv2i
        jsr print
        jmp prompt

view:   jsr v2i_init
        lda #<LOADBUF
        ldy #>LOADBUF
        jsr v2i_show
        bcc :+
        pha                             ; not for this machine (PAL/NTSC)
        jsr v2i_exit
        pla
        jsr v2i_errmsg
        jsr print
        lda #13
        jsr CHROUT
        jmp prompt
:
.if FRAME
        lda #FRAME_COL
        jsr v2i_frame
.endif
        lda hastext
        beq :+
        lda #<TXTBUF
        ldy #>TXTBUF
        jsr v2t_draw
:       jsr v2i_start
        lda #$7f                        ; keyboard row 7: space = bit 4
        sta $dc00
@up:    lda $dc01                       ; wait for release, then press
        and #$10
        beq @up
@down:  lda $dc01
        and #$10
        bne @down
        jsr v2i_exit                     ; give the machine back to the KERNAL
@flush: jsr GETIN                       ; drop the space from the key buffer
        bne @flush
        jmp prompt

loadtext:                               ; load the text file set by SETNAM to TXTBUF; if it
        ldx #<TXTBUF                    ; is a .v2t, set hastext
        ldy #>TXTBUF
        jsr loadfile
        bcs @no
        ldx #3
:       lda TXTBUF,x
        cmp tmagic,x
        bne @no
        dex
        bpl :-
        inc hastext
@no:    rts

loadfile:                               ; load the file set by SETNAM to X/Y; C=1 on error
        stx vptr
        sty vptr+1
        lda #1
        ldx $ba                         ; last used device, default 8
        cpx #8
        bcs :+
        ldx #8
:       ldy #0                          ; secondary 0: load to X/Y, not the file's address
        jsr SETLFS
        lda #0
        ldx vptr
        ldy vptr+1
        jmp LOAD

print:  sta vptr                        ; print zero-terminated string at A/Y
        sty vptr+1
        ldy #0
@p:     lda (vptr),y
        beq @done
        jsr CHROUT
        iny
        bne @p
@done:  rts

magic:  .byte "V2I", 3
tmagic: .byte "V2T", 4
txtext: .byte ".TXT"
msg_prompt:
        .byte 13, "V2I VIEWER - FILE NAME (EMPTY = QUIT)", 13, "? ", 0
msg_loading:
        .byte "LOADING...", 13, 0
msg_ioerr:
        .byte "LOAD ERROR", 13, 0
msg_notv2i:
        .byte "NOT A V2I FILE", 13, 0
name:   .res 17
.if DUAL
suffix: .byte "-P.V2I", "-N.V2I"
namebuf: .res 16
dualname: .byte 0                       ; 1: the image was loaded as name + suffix
.endif

        .include "v2i.inc"
        .include "v2t.inc"
        .assert * <= LOADBUF, error, "viewer overlaps the image buffer"
