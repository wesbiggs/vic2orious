; vic2orious disk slideshow: loads the .v2i images (and their text files) listed in
; diskshow.inc from disk one after another with the KERNAL and shows each one for
; HOLD_SECS seconds (up to 1000, counted in frames: 50 a second on PAL, 60 on NTSC; 0:
; until space). Space shows the next image, RUN/STOP returns to BASIC. While an image
; loads the screen is black with a yellow floppy disk (sprite 0) in the middle (the
; KERNAL loader can't run beside a kernel, so the image can't stay up); the text screen,
; which still says what is loading (in black until then), comes back on an error and
; stays until an image shows again.
; Assembled with DUAL=1 it is for a disk with both PAL and NTSC images: it loads
; <name>-p.v2i or <name>-n.v2i, whichever suits the machine, and the text named for that
; machine in diskshow.inc (one shared, or <name>-p.txt / -n.txt when the layouts differ).

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
start:  lda $d020                       ; the text screen, for errors and the return
        sta orig_d020
        lda $d021
        sta orig_d021
        lda $d011
        sta orig_d011
        lda $0286
        sta orig_0286
        lda #0
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

load:   lda fails                       ; blank, unless an error message is up
        bne :+
        jsr blank
:       lda #<msg_loading
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
.if DUAL
        lda v2i_system
        cmp #V2I_NTSC
        bne :+
        ldy ntname_hi,x
        beq show
        lda ntname_lo,x
        jmp @tname
:
.endif
        ldy tname_hi,x
        beq show
        lda tname_lo,x
@tname: jsr fname
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
        jsr unblank
        lda #<msg_ioerr
        ldy #>msg_ioerr
        jsr print
        jmp skip
@bad:   jsr unblank
        lda #<msg_notv2i
        ldy #>msg_notv2i
        jsr print
skip:   inc fails
        lda fails
        cmp #SHOW_COUNT
        bcc advance
        lda #<msg_none
        ldy #>msg_none
        jsr print
quit:   jsr unblank
        jmp ($a002)                     ; BASIC warm start

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
        jsr unblank
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
        jsr v2i_exit                    ; give the machine back to the KERNAL (back
                                        ; to the floppy: v2i_init saved its registers)
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

DISK_BLOCK = 13                         ; the floppy sprite at $0340 (tape buffer)
DISK_COL  = 7                           ; yellow

blank:                                  ; black screen, black text, the floppy on
        lda #0
        sta $d020
        sta $d021
        sta $0286                       ; cursor colour: the load messages print black
        jsr colram
        ldx #62
:       lda disk_spr,x
        sta DISK_BLOCK * 64,x
        dex
        bpl :-
        lda $0288                       ; sprite 0 pointer, after the KERNAL's screen
        clc
        adc #>$03f8
        sta vptr+1
        lda #<$03f8
        sta vptr
        ldy #0
        lda #DISK_BLOCK
        sta (vptr),y
        lda #172                        ; centred: the 20x20 icon is at columns 2-21
        sta $d000
        lda #141
        sta $d001
        lda #$fe                        ; sprite 0: low X, unexpanded, hires, in front
        and $d010
        sta $d010
        lda #$fe
        and $d017
        sta $d017
        lda #$fe
        and $d01b
        sta $d01b
        lda #$fe
        and $d01c
        sta $d01c
        lda #$fe
        and $d01d
        sta $d01d
        lda #DISK_COL
        sta $d027
        lda #1
        sta $d015
        lda orig_d011                   ; display on (v2i_exit brings all of it back)
        and #$7f
        ora #$10
        sta $d011
        rts

unblank:                                ; the text screen as the program found it
        lda #0
        sta $d015
        lda orig_d020
        sta $d020
        lda orig_d021
        sta $d021
        lda orig_d011
        and #$7f
        sta $d011
        lda orig_0286
        sta $0286
colram: ldx #0                          ; colour RAM = A
:       sta $d800,x
        sta $d900,x
        sta $da00,x
        sta $dae8,x
        inx
        bne :-
        rts

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
orig_d020: .byte 0
orig_d021: .byte 0
orig_d011: .byte 0
orig_0286: .byte 0
disk_spr:                               ; a 5.25" floppy, 20x20 at columns 2-21
        .byte $1f,$ff,$f8,$3f,$ff,$fc,$3f,$ff,$fc,$3f,$ff,$fc,$3f,$ff,$f8,$3f,$ff,$f8
        .byte $3f,$c3,$f8,$3f,$81,$fc,$3f,$81,$fc,$3f,$81,$fc,$3f,$81,$fc,$39,$c3,$fc
        .byte $39,$ff,$fc,$3f,$e7,$fc,$3f,$c3,$fc,$3f,$c3,$fc,$3f,$c3,$fc,$3f,$c3,$fc
        .byte $3f,$e7,$fc,$1f,$ff,$f8,$00,$00,$00
magic:  .byte "V2I", 3
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
