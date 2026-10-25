; vic2orious disk slideshow: loads the .v2i images (and their text files) listed in
; diskshow.inc from disk one after another with the KERNAL and shows each one for
; HOLD_SECS seconds (up to 1000, counted in frames: 50 a second on PAL, 60 on NTSC; 0:
; until space). Space shows the next image, RUN/STOP returns to BASIC. While an image
; loads the text screen says which (the KERNAL loader can't run beside a kernel, so the
; image can't stay up).
; Assembled with DUAL=1 it is for a disk with both PAL and NTSC images: it loads
; <name>-p.v2i or <name>-n.v2i, whichever suits the machine (the texts are shared).

        .include "diskshow.inc"         ; generated: SHOW_COUNT, HOLD_SECS, file names

CHROUT  = $ffd2
SETLFS  = $ffba
SETNAM  = $ffbd
LOAD    = $ffd5
GETIN   = $ffe4
STOP    = $ffe1
FNLEN   = $b7                           ; SETNAM's length and pointer
FNADR   = $bb
LOADBUF = $2800                         ; images are loaded here (up to $97ff)
TXTBUF  = $9800                         ; text files are loaded here (up to $9fff; below
                                        ; the BASIC ROM, which is on when it is checked).
                                        ; The program, with its names, ends below $2800

.ifndef FRAME
FRAME = 0                               ; 1: frame the images (build -b)
.endif
.ifndef DUAL
DUAL = 0                                ; 1: image names get -p.v2i / -n.v2i
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
        sta hold
        sta hold+1
        jsr v2i_detect                  ; hold = HOLD_SECS * frames per second
        ldy #50
        lda v2i_system
        cmp #V2I_NTSC
        bne :+
        ldy #60
:       sty fps
        lda #<HOLD_SECS
        sta vptr
        lda #>HOLD_SECS
        sta vptr+1
@mul:   lda vptr
        ora vptr+1
        beq load
        clc
        lda hold
        adc fps
        sta hold
        bcc :+
        inc hold+1
:       lda vptr
        bne :+
        dec vptr+1
:       dec vptr
        jmp @mul

load:   lda #<msg_loading
        ldy #>msg_loading
        jsr print
        ldx cur
        lda name_lo,x
        ldy name_hi,x
        jsr iname
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
        bcc :+
        pha                             ; not for this machine (PAL/NTSC)
        jsr v2i_exit
        pla
        jsr v2i_errmsg
        jsr print
        lda #13
        jsr CHROUT
        jmp skip
:       lda #0
        sta fails
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

hook:   lda hold                        ; 0: until space
        ora hold+1
        beq @keys
        inc frame
        bne :+
        inc frameh
:       lda frame                       ; frameh/frame >= hold: next image
        cmp hold
        lda frameh
        sbc hold+1
        bcc @keys
        lda #1
        sta req
@keys:  lda #$7f                        ; keyboard row 7: space = bit 4, RUN/STOP = bit 7
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

iname:                                  ; SETNAM for the image whose name is at A/Y
.if DUAL
        sta vptr                        ; name + "-P.V2I" or "-N.V2I" in namebuf
        sty vptr+1
        ldy #0
        lda (vptr),y
        tax
:       iny
        lda (vptr),y
        sta namebuf-1,y
        dex
        bne :-
        ldx #0
        lda v2i_system
        cmp #V2I_NTSC
        bne :+
        ldx #8
:       lda suffix,x
        sta namebuf,y
        inx
        iny
        txa
        and #7
        cmp #6
        bne :-
        tya                             ; (copied up to suffix index 6 or 14)
        ldx #<namebuf
        ldy #>namebuf
        jmp SETNAM
.endif
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

.if DUAL
suffix: .byte "-P.V2I", 0, 0, "-N.V2I"
namebuf: .res 16
.endif
hold:   .word 0                         ; frames per image (0: until space)
fps:    .byte 0
magic:  .byte "V2I", 2
tmagic: .byte "V2T", 4
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
        .assert * <= LOADBUF, error, "diskshow overlaps the image buffer"
