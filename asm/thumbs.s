; vic2orious thumbnails: browses the .v2i images on the disk without loading them. It
; reads the directory (again on D, after a disk change) and takes every file whose name ends in ".v2i" (up to
; MAX_NAMES), except those ending in the other video system's "-n.v2i" / "-p.v2i" (the
; dual disk's), in directory order. A .v2i starts with its header, thumbnail and
; metadata, so for each image only those are read (KERNAL OPEN/CHRIN, about 600 bytes of a
; 10-20K file) when it is shown; the thumbnail is shown with v2i_thumb (up to 8 sprites
; on top of each other, no raster tricks) beside the header's facts and the metadata.
; Keys: space or cursor right: next image, cursor left: previous one, return: load the whole
; image and show it (space comes back), D: read the directory again (another disk),
; RUN/STOP: back to BASIC. VERIFY=1 (build
; --verify): all text in black, so a screenshot shows only the first image's thumbnail.
; BASIC is banked out while it runs: the names are kept under the BASIC ROM.

        .macpack longbranch

CHROUT  = $ffd2
CHRIN   = $ffcf
SETLFS  = $ffba
SETNAM  = $ffbd
OPEN    = $ffc0
CLOSE   = $ffc3
CHKIN   = $ffc6
CLRCHN  = $ffcc
LOAD    = $ffd5
GETIN   = $ffe4
STATUS  = $90
FNLEN   = $b7                           ; SETNAM's length and pointer
FNADR   = $bb
LOADBUF = $2800                         ; the start of a .v2i is read here, a whole one
                                        ; loaded here (up to $97ff)
SPRBUF  = $3e00                         ; thumbnail sprite blocks (248-255, VIC bank 0)
SCREEN  = $0400                         ; the KERNAL's text screen
COLRAM  = $d800
META_ROW = 7                            ; metadata rows META_ROW..21
META_END = 22
FOOT_ROW = 24
THUMB_COL = 1                           ; thumbnail cells: columns 1-3, rows 1-3
THUMB_ROW = 1
INFO_COL = 5
NAMES   = $a000                         ; directory names, 17 bytes each (length, up to
MAX_NAMES = 240                         ; 16 characters): up to $bfef
.ifndef VERIFY
VERIFY = 0
.endif
.if VERIFY
COL_NAME = 0
COL_TEXT = 0
COL_META = 0
COL_KEY  = 0
.else
COL_NAME = 1                            ; white
COL_TEXT = 15                           ; light grey
COL_META = 12                           ; grey
COL_KEY  = 3                            ; cyan: metadata keys
.endif

vptr    = $fb                           ; 2 bytes
wptr    = $fd                           ; 2 bytes: where rdn reads to
pp      = $f7                           ; putc's screen and colour RAM pointers (RS-232
cp      = $f9                           ; buffer pointers: free without RS-232)

        .segment "LOADADDR"
        .word $0801
        .segment "EXEHDR"
        .word @next, 10
        .byte $9e, "2061", 0
@next:  .word 0

        .code
start:  ldx #V2I_ZP_SIZE-1              ; BASIC's zero page, which v2i_info uses: back on
:       lda V2I_ZP,x                    ; exit
        sta savezp,x
        dex
        bpl :-
        lda $d018
        sta orig_d018
        lda #$80                        ; no case switch (shift + C=)
        sta $0291
        lda #$17                        ; lower case characters, screen at $0400
        sta $d018
        lda #0
        sta $d020
        sta $d021
        lda #$36                        ; BASIC out: the names live under it
        sta $01
        ldx $ba                         ; last used device, default 8
        cpx #8
        bcs :+
        ldx #8
:       stx device
        jsr v2i_detect                  ; which "-p/-n.v2i" to leave out, "not for this C64"
        ldx #'N'                        ; (PETSCII, as in the directory)
        lda v2i_system
        beq :+
        ldx #'P'
        cmp #V2I_NTSC
        beq :+
        ldx #0                          ; another VIC-II: none left out
:       stx othersys
reload: lda #0                          ; (D: a new disk)
        sta cur
        jsr draw_clear
        ldx #<msg_dir
        ldy #>msg_dir
        jsr puts
        jsr scan
        lda count
        bne browse
        jsr draw_clear                  ; nothing to show
        ldx #<msg_none
        ldy #>msg_none
        jsr puts
:       jsr GETIN
        beq :-
        jsr isd
        beq reload
        jmp quit
browse: jsr preview
redraw: jsr draw
keys:   jsr GETIN
        beq keys
        cmp #' '
        beq next
        cmp #$1d                        ; cursor right
        beq next
        cmp #$9d                        ; cursor left
        beq prev
        cmp #13
        beq view
        jsr isd
        beq reload
        cmp #3                          ; RUN/STOP
        bne keys
quit:   lda #0
        sta $d015
        lda #$37                        ; BASIC back
        sta $01
        lda orig_d018
        sta $d018
        lda #0
        sta $0291
        ldx #V2I_ZP_SIZE-1
:       lda savezp,x
        sta V2I_ZP,x
        dex
        bpl :-
        lda #147                        ; clear the screen
        jsr CHROUT
        jmp ($a002)                     ; BASIC warm start
isd:    cmp #'D'                        ; Z=1 for D (PETSCII, shifted or not)
        beq :+
        cmp #'D' | $80
:       rts
next:   ldx cur
        inx
        cpx count
        bcc :+
        ldx #0
:       stx cur
        jmp browse
prev:   ldx cur
        bne :+
        ldx count
:       dex
        stx cur
        jmp browse

; ---- return: load the whole file and show the image until space
view:   lda pstat
        bne keys                        ; not a .v2i
        lda #0                          ; (the load overwrites the sprite blocks)
        sta $d015
        jsr footer_clear
        ldx #<msg_loading
        ldy #>msg_loading
        jsr puts
        jsr iname
        lda #1
        ldx device
        ldy #0                          ; secondary 0: load to X/Y
        jsr SETLFS
        lda #0
        ldx #<LOADBUF
        ldy #>LOADBUF
        jsr LOAD
        jcs @ioerr
        jsr v2i_init
        lda #<LOADBUF
        ldy #>LOADBUF
        jsr v2i_show
        bcs @fail                       ; not for this machine
        jsr v2i_start
        lda #$7f                        ; keyboard row 7: space = bit 4
        sta $dc00
@up:    lda $dc01                       ; wait for release, then press
        and #$10
        beq @up
@down:  lda $dc01
        and #$10
        bne @down
@rel:   lda $dc01                       ; and released again: the KERNAL's keyboard scan
        and #$10                        ; would find it still down after v2i_exit and
        beq @rel                        ; put it in the key buffer (next image)
        jsr v2i_exit
:       jsr GETIN                       ; drop keys from the key buffer
        bne :-
        jmp redraw                      ; (LOADBUF starts with the same header, thumbnail
                                        ; and metadata; the sprite blocks were overwritten)
@fail:  pha
        jsr v2i_exit
        jsr footer_clear
        pla
        jsr v2i_errmsg
        tax
        jsr puts
        jmp keys
@ioerr: jsr footer_clear
        ldx #<msg_ioerr
        ldy #>msg_ioerr
        jsr puts
        jmp keys

; ---- read the start of image cur into LOADBUF: header, thumbnail, metadata. pstat: 0 ok,
; 1 read error, 2 not a version 5 .v2i
preview:
        lda #0
        sta $d015
        sta pstat
        jsr iname
        lda #2
        ldx device
        ldy #2                          ; a data channel: read it byte by byte
        jsr SETLFS
        jsr OPEN
        jcs @ioerr
        ldx #2
        jsr CHKIN
        jcs @ioerr
        lda #<LOADBUF                   ; the load address (dropped)
        sta wptr
        lda #>LOADBUF
        sta wptr+1
        lda #2
        ldx #0
        jsr rdn
        jcs @ioerr
        lda #<LOADBUF
        sta wptr
        lda #V2I_H_SIZE                 ; the header
        ldx #0
        jsr rdn
        jcs @ioerr
        ldx #3                          ; "V2I", version 5
:       lda LOADBUF,x
        cmp magic,x
        jne @notv2i
        dex
        bpl :-
        lda LOADBUF+V2I_H_FLAGS
        and #V2I_F_THUMB
        beq @meta
        lda #4                          ; thumbnail: size, background, n
        ldx #0
        jsr rdn
        jcs @ioerr
        ldy #0                          ; (wptr is past it: n is at wptr - 1)
        lda wptr
        sec
        sbc #1
        sta vptr
        lda wptr+1
        sbc #0
        sta vptr+1
        lda (vptr),y
        cmp #9
        jcs @notv2i
        lsr                             ; n * 64: high n >> 2, low n << 6
        lsr
        tax
        lda (vptr),y
        asl
        asl
        asl
        asl
        asl
        asl
        jsr rdn
        jcs @ioerr
@meta:  lda LOADBUF+V2I_H_FLAGS
        and #V2I_F_META
        beq @close
        lda wptr                        ; metadata: length, then the text
        sta vptr
        lda wptr+1
        sta vptr+1
        lda #2
        ldx #0
        jsr rdn
        jcs @ioerr
        ldy #1
        lda (vptr),y
        cmp #5                          ; at most 1024 (the format's limit)
        jcs @notv2i
        tax
        dey
        lda (vptr),y
        jsr rdn
        jcs @ioerr
        bcc @close
@notv2i:
        lda #2
        .byte $2c                       ; (bit abs: skips the lda)
@ioerr: lda #1
        sta pstat
@close: jsr CLRCHN
        lda #2
        jmp CLOSE

rdn:                                    ; read A + 256 * X bytes to (wptr); C=1 on an error
        sta cnt
        stx cnt+1
@l:     lda cnt
        ora cnt+1
        beq @ok
        jsr CHRIN
        ldy STATUS                      ; (this never reads a file's last byte: EOF is an
        bne @err                        ; error too)
        sta (wptr),y
        inc wptr
        bne :+
        inc wptr+1
:       lda cnt
        bne :+
        dec cnt+1
:       dec cnt
        jmp @l
@ok:    clc
        rts
@err:   sec
        rts

; ---- the screen for image cur from LOADBUF (and pstat)
draw:   jsr draw_clear
        jmp draw_name

draw_clear:                             ; blank screen, sprites off, cursor at row 1,
        lda #0                          ; column 1, in the text colour
        sta $d015
        ldx #0                          ; clear: spaces
:       lda #' '
        sta SCREEN,x
        sta SCREEN+$100,x
        sta SCREEN+$200,x
        sta SCREEN+$2e8,x
        lda #COL_TEXT
        sta COLRAM,x
        sta COLRAM+$100,x
        sta COLRAM+$200,x
        sta COLRAM+$2e8,x
        inx
        bne :-
        lda #COL_TEXT
        sta tcol
        ldx #1
        ldy #1
        jmp at

draw_name:
        ldx #THUMB_ROW                  ; the name, as on the disk (in lower case)
        ldy #INFO_COL
        jsr at
        lda #COL_NAME
        sta tcol
        ldy #0
:       cpy FNLEN
        beq :+
        lda (FNADR),y
        cmp #$41                        ; PETSCII A-Z: shown in lower case
        bcc @nc
        cmp #$5b
        bcs @nc
        ora #$20
@nc:    jsr putc
        iny
        bne :-
:       lda #COL_TEXT
        sta tcol
        ldx #<msg_of                    ; "  (n/count)"
        ldy #>msg_of
        jsr puts
        ldx cur
        inx
        txa
        ldx #0
        jsr pdec
        lda #'/'
        jsr putc
        lda count
        ldx #0
        jsr pdec
        lda #')'
        jsr putc
        jsr nl_info
        lda pstat
        beq @v2i
        ldx #<msg_ioerr
        ldy #>msg_ioerr
        cmp #1
        beq :+
        ldx #<msg_notv2i
        ldy #>msg_notv2i
:       jsr puts
        jmp foot
@v2i:   lda #<LOADBUF
        ldy #>LOADBUF
        jsr v2i_info
        bcc :+
        ldx #<msg_notv2i
        ldy #>msg_notv2i
        jsr puts
        jmp foot
:       lda v2i_cols                    ; "W x H hires|multicolour, PAL|NTSC"
        ldx #0                          ; (width in pixels: 8 per cell, 4 multicolour)
        stx num+1
        asl
        rol num+1
        asl
        rol num+1
        asl
        rol num+1
        ldx v2i_mc
        beq :+
        lsr num+1
        ror a
:       sta wid                         ; (for the share of wrong pixels)
        ldx num+1
        stx wid+1
        jsr pdec
        lda #'x'
        jsr putc
        lda v2i_rows
        asl
        asl
        asl
        ldx #0
        jsr pdec
        ldx #<msg_hires
        ldy #>msg_hires
        lda v2i_mc
        beq :+
        ldx #<msg_mc
        ldy #>msg_mc
:       jsr puts
        ldx #<msg_pal
        ldy #>msg_pal
        lda LOADBUF+V2I_H_SYS
        beq :+
        ldx #<msg_ntsc
        ldy #>msg_ntsc
:       jsr puts
        lda LOADBUF+V2I_H_SYS
        cmp v2i_system
        beq :+
        ldx #<msg_other
        ldy #>msg_other
        jsr puts
:       jsr nl_info                     ; "at column C, row R"
        ldx #<msg_at
        ldy #>msg_at
        jsr puts
        lda v2i_col
        ldx #0
        jsr pdec
        ldx #<msg_row
        ldy #>msg_row
        jsr puts
        lda v2i_row
        ldx #0
        jsr pdec
        jsr nl_info                     ; "P pixels not exact (S%)", "in L of H lines"
        lda LOADBUF+22                  ; (or "Pixel perfect")
        ora LOADBUF+23
        bne :+
        ldx #<msg_exact
        ldy #>msg_exact
        jsr puts
        jmp @thumb
:       lda LOADBUF+22
        ldx LOADBUF+23
        jsr pdec
        ldx #<msg_pixels
        ldy #>msg_pixels
        jsr puts
        jsr ppct
        ldx #<msg_pct
        ldy #>msg_pct
        jsr puts
        jsr nl_info
        ldx #<msg_in
        ldy #>msg_in
        jsr puts
        lda LOADBUF+20
        ldx LOADBUF+21
        jsr pdec
        ldx #<msg_ofl
        ldy #>msg_ofl
        jsr puts
        lda v2i_rows
        asl
        asl
        asl
        ldx #0
        jsr pdec
        ldx #<msg_lines
        ldy #>msg_lines
        jsr puts
@thumb:
        lda #<(24 + 8 * THUMB_COL)      ; the thumbnail, over its background colour
        sta v2i_tx
        lda #>(24 + 8 * THUMB_COL)
        sta v2i_tx+1
        lda #50 + 8 * THUMB_ROW
        sta v2i_ty
        lda #<SPRBUF
        ldy #>SPRBUF
        jsr v2i_thumb
        bcs @meta
        ldx #2                          ; 3x3 cells: reverse spaces in the background colour
:       sta COLRAM + 40 * THUMB_ROW + THUMB_COL,x
        sta COLRAM + 40 * (THUMB_ROW + 1) + THUMB_COL,x
        sta COLRAM + 40 * (THUMB_ROW + 2) + THUMB_COL,x
        pha
        lda #160
        sta SCREEN + 40 * THUMB_ROW + THUMB_COL,x
        sta SCREEN + 40 * (THUMB_ROW + 1) + THUMB_COL,x
        sta SCREEN + 40 * (THUMB_ROW + 2) + THUMB_COL,x
        pla
        dex
        bpl :-
@meta:  lda v2i_mptr+1                  ; the metadata, keys in their own colour
        beq foot
        sta vptr+1
        lda v2i_mptr
        sta vptr
        lda v2i_mlen
        sta cnt
        lda v2i_mlen+1
        sta cnt+1
        ldx #META_ROW
        ldy #0
        jsr at
        lda #COL_KEY
        sta tcol
        lda #1                          ; at a line's start
        sta lstart
@mc:    lda cnt
        ora cnt+1
        beq foot
        lda crow
        cmp #META_END
        bcs foot
        ldy #0
        lda (vptr),y
        cmp #':'
        bne :+
        ldx #COL_META                   ; the value
        stx tcol
:       cmp #$0a
        bne :+
        ldx #COL_KEY                    ; next line: a key
        stx tcol
        ldx #1
        stx lstart
        bne @put                        ; (always)
:       ldx lstart                      ; a key's first letter in upper case
        beq @put
        ldx #0
        stx lstart
        cmp #'a'
        bcc @put
        cmp #'z'+1
        bcs @put
        and #$df
@put:   jsr putc
        inc vptr
        bne :+
        inc vptr+1
:       lda cnt
        bne :+
        dec cnt+1
:       dec cnt
        jmp @mc
foot:   jsr footer_clear
        ldx #<msg_keys
        ldy #>msg_keys
        jmp puts

footer_clear:                           ; blank the bottom row, cursor at its start
        ldx #39
        lda #' '
:       sta SCREEN + 40 * FOOT_ROW,x
        dex
        bpl :-
        ldx #FOOT_ROW
        ldy #0
        jsr at
        lda #COL_TEXT
        sta tcol
        rts

nl_info:                                ; next row, at the info column
        ldx crow
        inx
        ldy #INFO_COL
        ; fall through
at:     stx crow                        ; cursor at row X, column Y
        sty ccol
        rts

puts:   stx vptr                        ; print the zero-terminated ASCII string at X/Y
        sty vptr+1
        ldy #0
:       lda (vptr),y
        beq :+
        jsr putc
        iny
        bne :-
:       rts

; ---- A (ASCII; $0a: new line) at the cursor, in colour tcol; wraps at the right edge.
; Keeps X and Y. Writes the screen directly (no scrolling, no logical lines): nothing is
; drawn below row 24
putc:   stx px
        sty py
        cmp #$0a
        beq @nl
        cmp #$60                        ; to a screen code (lower case set): a-z (and
        bcc :+                          ; `{|}~) -> 1-31, @ A-Z [\]^_ -> 0, 65-90, 27-31
        sbc #$60
        jmp @put
:       cmp #$40
        bcc @put
        beq @sub
        cmp #$5b
        bcc @put
@sub:   and #$1f
@put:   ldx crow
        cpx #25
        bcs @done
        pha
        lda rowlo,x
        sta pp
        sta cp
        lda rowhi,x
        sta pp+1
        clc
        adc #>(COLRAM - SCREEN)
        sta cp+1
        ldy ccol
        pla
        sta (pp),y
        lda tcol
        sta (cp),y
        inc ccol
        lda ccol
        cmp #40
        bcc @done
@nl:    lda #0
        sta ccol
        inc crow
@done:  ldx px
        ldy py
        rts

pdec:                                   ; A + 256 * X in decimal, without leading zeros
        sta num
        stx num+1
        ldy #4
        lda #0
        sta started
@dig:   ldx #'0'
@sub:   lda num
        sec
        sbc p10lo,y
        pha
        lda num+1
        sbc p10hi,y
        bcc @nd
        sta num+1
        pla
        sta num
        inx
        bne @sub
@nd:    pla
        cpx #'0'
        bne @out
        lda started
        bne @out
        cpy #0
        bne @skip
@out:   txa
        jsr putc
        inc started
@skip:  dey
        bpl @dig
        rts

;ppct: the wrong pixels (header) as a share of the image's (wid x 8 * v2i_rows: image
; pixels, wide ones in multicolour, as the converter counts them), "N.NN", rounded; at
; least 0.01 when any are wrong
ppct:   lda wid                         ; div = the image's pixels (at most 64000)
        sta mula
        lda wid+1
        sta mula+1
        lda v2i_rows
        asl
        asl
        asl
        sta mulb
        lda #0
        sta mulb+1
        jsr mul16
        lda prod
        sta div
        lda prod+1
        sta div+1
        lda LOADBUF+22                  ; prod = wrong * 10000 + div / 2
        sta mula
        lda LOADBUF+23
        sta mula+1
        lda #<10000
        sta mulb
        lda #>10000
        sta mulb+1
        jsr mul16
        lda div+1
        lsr a
        sta tmp
        lda div
        ror a
        clc
        adc prod
        sta prod
        lda tmp
        adc prod+1
        sta prod+1
        bcc :+
        inc prod+2
        bne :+
        inc prod+3
:       jsr div32                       ; hundredths of a per cent (wrong <= pixels: < 65536)
        lda prod
        ora prod+1
        bne :+
        inc prod
:       lda #100
        sta div
        lda #0
        sta div+1
        sta prod+2
        sta prod+3
        jsr div32
        lda prod
        ldx prod+1
        jsr pdec
        lda #'.'
        jsr putc
        lda rem
        ldx #'0'
:       cmp #10
        bcc :+
        sbc #10
        inx
        bne :-
:       pha
        txa
        jsr putc
        pla
        ora #'0'
        jmp putc

mul16:                                  ; prod (32 bits) = mula * mulb (mulb is lost)
        lda #0
        sta prod+2
        sta prod+3
        ldx #16
@l:     lsr mulb+1
        ror mulb
        bcc @s
        clc
        lda prod+2
        adc mula
        sta prod+2
        lda prod+3
        adc mula+1
        sta prod+3
@s:     ror prod+3
        ror prod+2
        ror prod+1
        ror prod
        dex
        bne @l
        rts

div32:                                  ; prod = prod / div (the quotient must fit 16
        lda #0                          ; bits), rem = the remainder
        sta rem
        sta rem+1
        ldx #32
@l:     asl prod
        rol prod+1
        rol prod+2
        rol prod+3
        rol rem
        rol rem+1
        bcs @sub                        ; 17 bits: more than div anyway
        lda rem
        cmp div
        lda rem+1
        sbc div+1
        bcc @n
@sub:   lda rem
        sec
        sbc div
        sta rem
        lda rem+1
        sbc div+1
        sta rem+1
        inc prod
@n:     dex
        bne @l
        rts

iname:                                  ; SETNAM for image cur
        ldx cur
        jsr nameaddr
        ldy #0
        lda (wptr),y
        pha
        ldx wptr
        ldy wptr+1
        inx
        bne :+
        iny
:       pla
        jmp SETNAM

nameaddr:                               ; wptr = NAMES + 17 * X
        stx wptr
        lda #0
        sta wptr+1
        asl wptr
        rol wptr+1
        asl wptr
        rol wptr+1
        asl wptr
        rol wptr+1
        asl wptr
        rol wptr+1
        txa
        clc
        adc wptr
        sta wptr
        lda wptr+1
        adc #>NAMES                     ; (NAMES is page aligned)
        sta wptr+1
        rts

; ---- the directory: count = the names of the .v2i files for this machine, at NAMES.
; Read as BASIC lists it ("$" with secondary 0): load address, then per line a link (0:
; the end), the blocks and the text, zero terminated; the name is between the first two
; quotes. The first line is the disk's name
scan:   lda #0
        sta count
        lda #1
        sta hdrline
        lda #1
        ldx #<dirname
        ldy #>dirname
        jsr SETNAM
        lda #2
        ldx device
        ldy #0
        jsr SETLFS
        jsr OPEN
        jcs @close
        ldx #2
        jsr CHKIN
        jcs @close
        jsr getb                        ; load address
        jsr getb
@line:  jsr getb                        ; link: 0 at the end (and on errors: getb gives 0)
        sta tmp
        jsr getb
        ora tmp
        jeq @close
        jsr getb                        ; blocks
        jsr getb
@q:     jsr getb                        ; to the first quote
        beq @line                       ; (a line without one: "blocks free")
        cmp #$22
        bne @q
        ldx count
        jsr nameaddr
        ldy #0
@n:     jsr getb
        beq @line
        cmp #$22
        beq @endn
        cpy #16
        bcs @n
        iny
        sta (wptr),y
        jmp @n
@endn:  tya
        ldy #0
        sta (wptr),y
@skip:  jsr getb                        ; the rest of the line
        bne @skip
        lda hdrline                     ; the disk's name
        beq :+
        dec hdrline
        jmp @line
:       ldy #0                          ; a .v2i? its last 4 characters ".V2I"
        lda (wptr),y
        cmp #5
        bcc @line
        tay
        ldx #3
:       lda (wptr),y
        cmp v2iext,x
        bne @line
        dey
        dex
        bpl :-
        cpy #2                          ; the other system's "-P"/"-N" before it?
        bcc @take
        lda (wptr),y
        cmp othersys
        bne @take
        dey
        lda (wptr),y
        cmp #'-'
        jeq @line
@take:  ldx count
        inx
        stx count
        cpx #MAX_NAMES
        jcc @line
@close: jsr CLRCHN
        lda #2
        jmp CLOSE

getb:   jsr CHRIN                       ; next directory byte; 0 after an error or the end
        ldx STATUS
        beq :+
        lda #0
:       cmp #0
        rts

othersys:                               ; the letter of the system whose files to leave out
        .byte 0
rowlo:
        .repeat 25, i
        .byte <(SCREEN + 40 * i)
        .endrepeat
rowhi:
        .repeat 25, i
        .byte >(SCREEN + 40 * i)
        .endrepeat
p10lo:  .byte <1, <10, <100, <1000, <10000
p10hi:  .byte >1, >10, >100, >1000, >10000

magic:  .byte "V2I", V2I_VERSION
v2iext: .byte ".V2I"
dirname: .byte "$"
msg_dir: .byte "Reading the directory...", 0
msg_none: .byte "No .v2i files on this disk.", $0a, $0a, " D: read again, any other key: quit.", 0
msg_of: .byte "  (", 0
msg_hires: .byte " hires, ", 0
msg_mc: .byte " multicolour, ", 0
msg_pal: .byte "PAL", 0
msg_ntsc: .byte "NTSC", 0
msg_other: .byte " (not this C64)", 0
msg_at: .byte "At column ", 0
msg_row: .byte ", row ", 0
msg_exact: .byte "Pixel perfect", 0
msg_pixels: .byte " pixels not exact (", 0
msg_pct: .byte "%)", 0
msg_in: .byte "in ", 0
msg_ofl: .byte " of ", 0
msg_lines: .byte " lines", 0
msg_ioerr: .byte "Cannot read the file", 0
msg_notv2i: .byte "Not a .v2i file (version 5)", 0
msg_loading: .byte "Loading the image...", 0
msg_keys: .byte "SPACE next RETURN view D disk STOP quit", 0

cur:    .byte 0                         ; image shown
pstat:  .byte 0                         ; preview: 0 read, 1 read error, 2 not a .v2i
device: .byte 8
count:  .byte 0                         ; images (names at NAMES)
hdrline: .byte 0
tmp:    .byte 0
cnt:    .word 0
num:    .word 0
wid:    .word 0
mula:   .word 0
mulb:   .word 0
div:    .word 0
rem:    .word 0
prod:   .res 4
started: .byte 0
lstart: .byte 0
crow:   .byte 0                         ; text cursor
ccol:   .byte 0
tcol:   .byte 0
px:     .byte 0
py:     .byte 0
orig_d018: .byte 0

        .include "v2i.inc"
savezp: .res V2I_ZP_SIZE
        .data                           ; the end of the program (the names are data)
        .assert * <= LOADBUF, error, "thumbs overlaps the image buffer"
