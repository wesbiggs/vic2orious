# vic2orious: first release

Turn any picture into a C64 hires or multicolour bitmap with multiplexed sprites, played by a cycle-exact kernel on PAL and NTSC, plus a proportional text library and demos.

## New
- **v2i images and v2t text:** hires bitmap plus per-line multiplexed sprites with a cycle-exact kernel; `v2i.inc` and `v2t.inc` libraries, a slideshow, a disk viewer, an interactive ask demo and single-library demos.
- **Multicolour images:** `img2c64 -m` makes 160-pixel-wide pictures with three colours per 4x8 cell plus black; X-expanded sprites paint the rest. Floyd-Steinberg photos come out at 0-1.6% wrong pixels (hires: about 10%). Centred, without text or frame.
- **PAL and NTSC:** build for either (`make NTSC=1`) or a dual disk with both (`make DUAL=1`); the dual demo PRG picks its image by `v2i_system`.
- **Full-size images:** up to 320x200, anywhere on screen (9-bit sprite X), including 200-line images on NTSC; images with no text are centred.
- **img2c64:** reads anything Pillow reads (HEIC with pillow-heif), applies EXIF orientation and ICC profiles, corrects for PAL/NTSC pixel aspect and fits a box (`-s WxH`).
- **TV palette by default:** colours are chosen as a real TV shows them (`tools/tv.vpl`, measured from a photo of a TV showing a colour bar, much paler than VICE's Colodore); `-P FILE.vpl` uses another screen's palette and `-P none` uses Colodore.
- **Dither picker:** without `-d`, img2c64 picks the dither for each picture and system, ranked by blurred SSIM and colour error (`-w R,S,C`), logging each dither's scores. A quick estimate of the converter ranks them first and only the best 3 are converted (`-t N`, `-t all` for every one); `analysis/dither_rank.py` ranks one picture's settings.
- **Dither modes:** `fs:K`, `atkinson[:K]` and `hybrid[:E]`, plus `-c S` to match palette saturation and `-l N`, a per-line run budget for hybrid. On five Kodak photos, hybrid gives 2.4% wrong pixels and a blurred RMS of 13.09, against Floyd-Steinberg's 9.9% and 13.59.
- **One picture, one PRG:** `python3 -m vic2.prg PICTURE` (`make prg PIC=...`) builds a single PRG for PAL and NTSC; `--verify` checks both in VICE.
- **Disk slideshow:** `diskshow` loads each image and its text from a .d64 or .d81, showing a floppy icon while it loads (10 s default hold).
- **Metadata block:** .v2i files carry the conversion settings; `python3 -m vic2.info` prints them.
- **Thumbnails:** img2c64 stores a 24x21 thumbnail in each PNG (at most 8 colours over black, shown exactly by up to 8 overlaid sprites) and the build puts it in the .v2i, making one from the PNG if img2c64 did not. `v2i_info` and `v2i_thumb` read and show it with the KERNAL on; the `thumbnails` program (`make run-thumbs`) browses the `.v2i` files in any disk's directory by thumbnail and metadata, reading only the start of each file (D reads the directory again after a disk change). Images are written to disk as `name.v2i`; the viewer accepts the name with or without `.v2i`. `make pictures` (`python3 -m vic2.disk`) puts the built `.v2i` files on a disk of their own with the browser (`VIEWER=1`: and the viewer and stories; `NTSC=1`, `DUAL=1`).
- **GEOS fonts** for v2t (`make FONT=...`; bring your own, none are included).
- **Demos:** smooth scroll (`make run-scroll`) and a stream demo with C64-side word wrap (`make run-stream`).
- **Build:** per-image conversion cache with `make -j`, `FAST=1` for instant disk loading in VICE, and a `_sprites.png` view of sprite use for each conversion.
- **File formats:** .v2i version 5 (hires and multicolour; thumbnail and metadata before the kernel), and .v2t version 4.
