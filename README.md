# vic2orious

Turns small pictures into Commodore 64 hires graphics that use far more colours per 8x8
cell than the hardware allows: every raster line, the 8 hardware sprites are recoloured
and moved to paint the pixels the bitmap cannot. Pictures can come with a short story,
drawn next to the image in a proportional version of the C64 font.

## Requirements

- Python 3 with [Pillow](https://pypi.org/project/pillow/)
- [cc65](https://cc65.github.io/) (`cl65`)
- [VICE](https://vice-emu.sourceforge.io/) (`x64sc`, `c1541`), installed with Homebrew
  (the build reads its palette and character ROM from `/opt/homebrew/share/vice/C64/`)

## 1. Prepare an image

Images must use the 16 C64 colours (Pepto palette), with width and height multiples of 8
(at most 256x200). Smaller and simpler images convert better; dithering hurts.

`tools/png2c64.py` maps any picture to the C64 palette. Resize the picture to the size you
want first, then:

```bash
python3 tools/png2c64.py picture.png -o input/name.png    # one picture
python3 tools/png2c64.py "pics/*.png" -o input/           # many, keeping their names
```

- `-o` takes a file name (default `out.png`) or a directory (one that exists, or a path
  ending in `/`), where each picture keeps its name with a `.png` extension. Several
  inputs or a glob pattern need a directory.
- `-d none` turns off dithering. The default, `-d floydsteinberg`, often looks better on
  photos, but dithered images are harder to convert exactly, so try both.
- For a frame around the picture, don't draw one into the image: build with
  `make FRAME=1`, and the C64 draws it.

## 2. Add a story (optional)

Put the text in `input/<name>.txt`: paragraphs separated by blank lines, a first line
starting with `# ` becomes the title. It is wrapped to the space right of the image (or
below a very wide image); the build tells you if it does not fit.

## 3. Questions for the ask demo (optional)

`input/<name>.ask` turns the image into a small interactive scene: a menu of topics beside
the picture, picked with the number keys, each answered in text drawn while the picture
stays on screen. Format: a first line `# TITLE`, paragraphs introducing the scene, then
for each topic a line `> K label` (K is the key, 1-9) followed by the answer's paragraphs.
`input/princess.ask` is an example.

## 4. Build

```bash
make                                  # all images in input/
make IMAGES="input/a.png input/b.png" # or just these
make FRAME=1                          # frame the images (row 1, column 1)
make AT=2,3                           # place the images at character column 2, row 3
make -j8                              # convert up to 8 images at once
make convert                          # only convert the images (build/<name>.v2i)
make verify                           # build and compare every screen with VICE
make clean
```

Further options: `LEADING=n` (pixel lines between text lines, default 2), `AUTO=n`
(frames per slideshow image, default 250; 0: only space changes the image) and
`HOLD=n` (seconds diskshow shows each image, default 15; 0: until space) and
`DISK=d64|d81`. `make help` lists everything. The Makefile runs `python3 -m vic2.build`
(see `python3 -m vic2.build --help`) and rebuilds only when inputs or options change.

Each image is converted once. `build/<name>.json` records what the conversion depended on
(the image, its story, the options, the converter sources), and later builds reuse the
`.v2i` while all that stays the same, so adding an image or editing a story only converts
that one. `python3 -m vic2.build --force` converts everything again.

For every image the build prints how many lines and pixels could not be reproduced
exactly, and writes `build/<name>_compare.png` (source | C64 result | wrong pixels in
red). Outputs:

- `build/slideshow.prg`: the images in one program; space for the next image, otherwise
  they change every 5 seconds. Only 3-4 images fit; with more, it takes the first ones
  that fit and says so.
- `build/diskshow.prg`: the same slideshow for any number of images, loading each one
  (and its story) from disk in turn and showing it for `HOLD` seconds (space: next).
  Loading uses the KERNAL, so it is slow (around half a minute per image with true drive
  emulation), and the image can't stay up meanwhile: the text screen says what is
  loading. RUN/STOP returns to BASIC.
- `build/ask-<name>.prg`: the ask demo for every image with an `.ask` file.
- `build/v2i-demo.prg`, `build/v2t-demo.prg`: the smallest programs using just one of the
  two libraries (an image; text without an image).
- `build/vic2orious.d64`: disk with `viewer`, `diskshow`, `slideshow`, the demos, and
  every image and story as separate files. When they do not fit on a 1541 disk (about 13
  images) it is `build/vic2orious.d81` (1581, about 60 images) instead.

## 5. Watch

```bash
make run                              # the slideshow
make run-diskshow                     # the disk slideshow (all images)
make run-viewer IMAGE=princess        # the disk viewer, with the image name typed in
make run-ask ASK=princess             # the ask demo
make run-v2i                          # image only
make run-v2t                          # text only
make run-d64                          # boot the disk (.d64 or .d81; starts the viewer)
```

In the viewer, type an image name. Space returns to the prompt; an empty name quits. In
the ask demo, the number keys pick topics and space returns to BASIC.

## Using the images in your own program

The C64 side is two independent ca65 libraries:

- `asm/v2i.inc` shows a `.v2i` image and gives the machine back afterwards
  ([docs/v2i-lib.md](docs/v2i-lib.md), format: [docs/v2i-format.md](docs/v2i-format.md)).
- `asm/v2t.inc` draws `.v2t` text files and single lines of proportional text into any
  hires bitmap, also while an image is displayed ([docs/v2t-lib.md](docs/v2t-lib.md),
  format and font: [docs/v2t-format.md](docs/v2t-format.md)).

## License

Copyright 2026 Wes Biggs. Licensed under the [Apache License, Version 2.0](LICENSE).

The font is generated at build time from the C64 character ROM that comes with VICE; it is
not part of this repository.
