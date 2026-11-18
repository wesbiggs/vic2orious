# vic2orious: first release

Turn any picture into a C64 hires or multicolour bitmap with multiplexed sprites, played by a cycle-exact kernel on PAL and NTSC, plus a proportional text library and demos.

## New
- **Choice of VIC bank (format version 6):** `build --bank 1|2|3` (`make BANK=`) picks the bank the programs show images in, and `v2i_bank` selects it at run time. Version 6 files are bank-agnostic: destinations are bank-relative and the kernel has a relocation table for its sprite pointers, so one `.v2i` shows in any bank. Bank 1 works for images that load outside `$4000-$7fff` (the v2i demo with a 14K program; the viewer and diskshow load at `$2800` and cannot yet); bank 2 is limited to 48 sprite blocks (VIC banks 0 and 2 show the character ROM at `$9000-$9fff`).
- **v2i images and v2t text:** hires bitmap plus per-line multiplexed sprites with a cycle-exact kernel; `v2i.inc` and `v2t.inc` libraries, a slideshow, a disk viewer, an interactive ask demo and single-library demos.
- **Multicolour images:** `img2c64 -m` makes 160-pixel-wide pictures with three colours per 4x8 cell plus black; X-expanded sprites paint the rest. Floyd-Steinberg photos come out at 0-1.6% wrong pixels (hires: about 10%). Centred, without text or frame.
- **PAL and NTSC:** build for either (`make NTSC=1`) or a dual disk with both (`make DUAL=1`); the dual demo PRG picks its image by `v2i_system`.
- **Full-size images:** up to 320x200, anywhere on screen (9-bit sprite X), including 200-line images on NTSC; images with no text are centred.
- **img2c64:** reads anything Pillow reads (HEIC with pillow-heif), applies EXIF orientation and ICC profiles, corrects for PAL/NTSC pixel aspect and fits a box (`-s WxH`).
- **TV palette by default:** colours are chosen as a real TV shows them (`tools/tv.vpl`, measured from a photo of a TV showing a colour bar, much paler than VICE's Colodore); `-P FILE.vpl` uses another screen's palette and `-P none` uses Colodore.
- **Dither picker:** without `-d`, img2c64 picks the dither for each picture and system, ranked by blurred SSIM and colour error (`-w R,S,C`), logging each dither's scores. A quick estimate of the converter ranks them first and only the best 3 are converted (`-t N`, `-t all` for every one); `analysis/dither_rank.py` ranks one picture's settings.
- **Dither modes:** `fs:K`, `atkinson[:K]` and `hybrid[:E]`, plus `-c S` to match palette saturation and `-l N`, a per-line run budget for hybrid. On five Kodak photos, hybrid gives 2.4% wrong pixels and a blurred RMS of 13.09, against Floyd-Steinberg's 9.9% and 13.59.
- **One picture, one PRG:** `python3 -m vic2.prg PICTURE` (`make prg PIC=...`) builds a single PRG for PAL and NTSC; `--verify` checks both in VICE. It also takes built `.v2i` files with their texts (`make prg PIC='x.v2i x.v2t'`): one image, or a PAL and an NTSC one in a dual PRG.
- **Disk slideshow:** `diskshow` loads each image and its text from a .d64 or .d81, showing a floppy icon while it loads (10 s default hold).
- **Metadata block:** .v2i files carry the conversion settings; `python3 -m vic2.info` prints them.
- **Thumbnails:** img2c64 stores a 24x21 thumbnail in each PNG (at most 8 colours over black, shown exactly by up to 8 overlaid sprites) and the build puts it in the .v2i, making one from the PNG if img2c64 did not. `v2i_info` and `v2i_thumb` read and show it with the KERNAL on; the `thumbnails` program (`make run-thumbs`) browses the `.v2i` files in any disk's directory by thumbnail and metadata, reading only the start of each file (D reads the directory again after a disk change). Images are written to disk as `name.v2i`; the viewer accepts the name with or without `.v2i`. `make pictures` (`python3 -m vic2.disk`) puts the built `.v2i` files on a disk of their own with the browser (`VIEWER=1`: and the viewer and stories; `NTSC=1`, `DUAL=1`).
- **Whitespace in stories:** extra blank lines, indents and runs of spaces in `.txt`/`.ask` text are kept; a no-break space joins words.
- **Text under wide images:** the empty row between image and text is left out when it would leave no room for one line of the font (a 320x184 image now takes NLQ 10-14 in its last two rows).
- **`.v2t` file names:** packed texts are `<name>.v2t` in the build and `NAME.V2T` on disk (were `.txt.prg` and `NAME.TXT`, which were not text files); rebuild disks made before.
- **GEOS fonts** for v2t (`make FONT=...`; bring your own, none are included).
- **Demos:** smooth scroll (`make run-scroll`) and a stream demo with C64-side word wrap (`make run-stream`).
- **Build:** per-image conversion cache with `make -j`, `FAST=1` for instant disk loading in VICE, and a `_sprites.png` view of sprite use for each conversion.
- **CI and releases:** GitHub Actions builds everything and verifies it pixel for pixel in a headless VICE on pushes to main and pull requests; a `v*` tag publishes the dual disk, PAL and NTSC programs and the libraries. `VICE_DATA` points the build at VICE's data directory on any system.
- **File formats:** .v2i version 5 (hires and multicolour; thumbnail and metadata before the kernel), and .v2t version 4.
