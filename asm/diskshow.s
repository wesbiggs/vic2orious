; vic2orious disk slideshow: loads the .v2i images (and their text files) listed in
; diskshow.inc from disk one after another with the KERNAL and shows each one for
; HOLD_FRAMES frames (up to 65535; 0: until space). Space shows the next image, RUN/STOP
; returns to BASIC. While an image loads the text screen says which (the KERNAL loader
; can't run beside a kernel, so the image can't stay up).

        .include "diskshow.inc"         ; generated: SHOW_COUNT, HOLD_FRAMES, file names

CHROUT  = $ffd2
SETLFS  = $ffba
SETNAM  = $ffbd
LOAD    = $ffd5
GETIN   = $ffe4
STOP    = $ffe1
FNLEN   = $b7                           ; SETNAM's length and pointer
FNADR   = $bb
LOADBUF = $2000                         ; images are loaded here (up to $bfff)
TXTBUF  = $1800                         ; text files are loaded here (after the program)

.ifndef FRAME
FRAME = 0                               ; 1: frame the images (build -b)
.endif
FRAME_COL = $10                         ; frame cells: white on black
frame   = $06                           ; frames shown, low byte
cur     = $07
fails   = $08                           ; images that failed to load in a row
hastext = $09
req     = $0a                           ; set by the hook: keys pressed ($80 RUN/STOP), or 1
keyprev = $0b
frameh  = $0c                           ; frames shown, high byte
vptr    = $fb                           ; 2 bytes

        .segment "LOADADDR"
        .word $0801
        .segment "EXEHDR"
        .word @next, 10
        .byte $9e, "2061", 0
@next:  .word 0

        .code
start:  lda #0
        sta cur
        sta fails
load:   lda #<msg_loading
        ldy #>msg_loading
        jsr print
        ldx cur
        lda name_lo,x
        ldy name_hi,x
        jsr fname
        ldy #0                          ; print the name
:       cpy FNLEN
        beq :+
        lda (FNADR),y
        jsr CHROUT
        iny
        bne :-
:       lda #13
        jsr CHROUT
        ldx #<LOADBUF
        ldy #>LOADBUF
        jsr loadfile
        bcs @err
        ldx #3                          ; "V2I" + version
:       lda LOADBUF,x
        cmp magic,x
        bne @bad
        dex
        bpl :-
        lda #0
        sta hastext
        ldx cur
        ldy tname_hi,x
        beq show
        lda tname_lo,x
        jsr fname
        ldx #<TXTBUF
        ldy #>TXTBUF
        jsr loadfile
        bcs show                        ; no text then
        ldx #3
:       lda TXTBUF,x
        cmp tmagic,x
        bne show
        dex
        bpl :-
        inc hastext
        bne show
@err:   jsr STOP                        ; RUN/STOP during the load
        beq quit
        lda #<msg_ioerr
        ldy #>msg_ioerr
        jsr print
        jmp skip
@bad:   lda #<msg_notv2i
        ldy #>msg_notv2i
        jsr print
skip:   inc fails
        lda fails
        cmp #SHOW_COUNT
        bcc advance
        lda #<msg_none
        ldy #>msg_none
        jsr print
quit:   jmp ($a002)                     ; BASIC warm start

show:   lda #0
        sta fails
        sta frame
        sta frameh
        sta req
        sta keyprev                     ; as if pressed: a key must be released first
        jsr v2i_init
        lda #<hook
        sta v2i_hook
        lda #>hook
        sta v2i_hook+1
        lda #<LOADBUF
        ldy #>LOADBUF
        jsr v2i_show
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
:       lda req
        beq :-
        jsr v2i_exit                    ; give the machine back to the KERNAL
:       jsr GETIN                       ; drop keys from the key buffer
        bne :-
        lda req
        bmi quit
advance:
        ldx cur
        inx
        cpx #SHOW_COUNT
        bcc :+
        ldx #0
:       stx cur
        jmp load

hook:
.if HOLD_FRAMES
        inc frame
        bne :+
        inc frameh
:       lda frame                       ; frameh/frame >= HOLD_FRAMES: next image
        cmp #<HOLD_FRAMES
        lda frameh
        sbc #>HOLD_FRAMES
        bcc :+
        lda #1
        sta req
:
.endif
        lda #$7f                        ; keyboard row 7: space = bit 4, RUN/STOP = bit 7
        sta $dc00
        lda $dc01
        and #$90
        tax
        eor #$90
        and keyprev                     ; pressed now (0) and released before (1)
        beq :+
        sta req
:       stx keyprev
        rts

fname:  sta vptr                        ; SETNAM with the length-prefixed name at A/Y
        sty vptr+1
        ldy #0
        lda (vptr),y
        inc vptr
        bne :+
        inc vptr+1
:       ldx vptr
        ldy vptr+1
        jmp SETNAM

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

magic:  .byte "V2I", 1
tmagic: .byte "V2T", 3
msg_loading:
        .byte "LOADING ", 0
msg_ioerr:
        .byte "LOAD ERROR", 13, 0
msg_notv2i:
        .byte "NOT A V2I FILE", 13, 0
msg_none:
        .byte "NO IMAGE COULD BE LOADED", 13, 0

        .include "v2i.inc"
        .include "v2t.inc"
        .data                           ; the end of the program (the names are data)
        .assert * <= TXTBUF, error, "diskshow overlaps the text buffer"
