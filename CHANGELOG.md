# vic2orious: first release

Turn any picture into a C64 hires bitmap with multiplexed sprites, played by a cycle-exact kernel on PAL and NTSC, plus a proportional text library and demos.

## New
- **v2i images and v2t text:** hires bitmap plus per-line multiplexed sprites with a cycle-exact kernel; `v2i.inc` and `v2t.inc` libraries, a slideshow, a disk viewer, an interactive ask demo and single-library demos.
- **PAL and NTSC:** build for either (`make NTSC=1`) or a dual disk with both (`make DUAL=1`); the dual demo PRG picks its image by `v2i_system`.
- **Full-size images:** up to 320x200, anywhere on screen (9-bit sprite X), including 200-line images on NTSC; images with no text are centred.
- **img2c64:** reads anything Pillow reads (HEIC with pillow-heif), applies EXIF orientation and ICC profiles, corrects for PAL/NTSC pixel aspect and fits a box (`-s WxH`).
- **TV palette by default:** colours are chosen as a real TV shows them (`tools/tv.vpl`, measured from a photo of a TV showing a colour bar, much paler than VICE's Colodore); `-P FILE.vpl` uses another screen's palette and `-P none` uses Colodore.
- **Dither picker:** without `-d`, img2c64 picks the dither for each picture and system, ranked by blurred SSIM and colour error (`-w R,S,C`); `analysis/dither_rank.py` ranks one picture's settings.
- **Dither modes:** `fs:K`, `atkinson[:K]` and `hybrid[:E]`, plus `-c S` to match palette saturation and `-l N`, a per-line run budget for hybrid. On five Kodak photos, hybrid gives 2.4% wrong pixels and a blurred RMS of 13.09, against Floyd-Steinberg's 9.9% and 13.59.
- **One picture, one PRG:** `python3 -m vic2.prg PICTURE` (`make prg PIC=...`) builds a single PRG for PAL and NTSC; `--verify` checks both in VICE.
- **Disk slideshow:** `diskshow` loads each image and its text from a .d64 or .d81, showing a floppy icon while it loads (10 s default hold).
- **Metadata block:** .v2i files carry the conversion settings; `python3 -m vic2.info` prints them.
- **GEOS fonts** for v2t (`make FONT=...`; bring your own, none are included).
- **Demos:** smooth scroll (`make run-scroll`) and a stream demo with C64-side word wrap (`make run-stream`).
- **Build:** per-image conversion cache with `make -j`, `FAST=1` for instant disk loading in VICE, and a `_sprites.png` view of sprite use for each conversion.
- **File formats:** .v2i version 3 and .v2t version 4.
