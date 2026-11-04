# analysis

One-off measurements of the converter. They are not part of the build.

## Requirements

- Everything the build needs: Python 3 with Pillow, and the `vic2` package from this repo.
  The scripts find it from their own path, so they run from any directory.
- numpy.
- `compare.py` also needs these:
  - [pynuvie](https://github.com/anarkiwi/pynuvie), a NUFLI encoder/decoder:
    `pip install 'pynuvie[image]'`. A venv is easiest.
  - [retropixels](https://github.com/micheldebree/retropixels) 0.9.11, the AFLI converter:
    `npm install -g retropixels@0.9.11`. Alternatively, set `RETROPIXELS` to the command
    that runs it, e.g. `RETROPIXELS="npx --prefix /some/dir retropixels"`.

## Test images

Both scripts read every PNG in a source directory (default `build/analysis/src`) and write
under `build/analysis/`. The images in the tables below were made like this:

```bash
mkdir -p build/analysis/src
```

```bash
python3 -c "from PIL import Image; Image.open('input/dragon.png').crop((24, 0, 320, 200)).save('build/analysis/src/dragon.png')"
```

```bash
for k in 01 05 23; do python3 tools/img2c64.py -a pal -s 296x200 -o build/analysis/src/kodim$k-fs.png images/kodak-full/kodim$k.png; python3 tools/img2c64.py -a pal -s 296x200 -d none -o build/analysis/src/kodim$k-none.png images/kodak-full/kodim$k.png; done
```

`img2c64` adds `-p` to the name of each image it writes. Remove it, or `image_source`
will look for a file that does not exist:

```bash
cd build/analysis/src && for f in *-p.png; do mv "$f" "${f%-p.png}.png"; done
```

Images are at most 296x200: the FLI tools get them at x = 24, right of the FLI bug columns.

## compare.py: v2i against AFLI and NUFLI

```bash
python analysis/compare.py [SRC_DIR]
```

What each tool gets:

- **vic2orious:** converts each image as it is (PAL, centred).
- **The FLI tools:** get the image on a black 320x200 canvas at x = 24, drawn in their own
  Pepto palette:
  - retropixels: hires FLI (AFLI) with `-r 0 -c rgb`, so no dither and no colour
    conversion.
  - pynuvie NUFLI: its default encoder, and again with `texture=0`, its lowest-error setting.

The score is wrong pixels versus the source, counted only over the image's own area. It
takes about 6.5 minutes for the seven images. The canvases and each tool's output are
written to `build/analysis/out/`.

The NUFLI numbers come from pynuvie's own decoder; a `.nuf` has no viewer, so they were not
run in VICE. For AFLI, retropixels' PNG matched its PRG in VICE (0 differing pixels).

Results (Nov 2026):

| image | pixels | v2i | AFLI (retropixels) | NUFLI (pynuvie) | NUFLI texture=0 |
|---|---|---|---|---|---|
| dragon | 59200 | 2029 (3.4%) | 3621 (6.1%) | 4880 (8.2%) | 4376 (7.4%) |
| kodim01-fs | 54464 | 6569 (12.1%) | 8943 (16.4%) | 15046 (27.6%) | 13587 (24.9%) |
| kodim01-none | 54464 | 146 (0.3%) | 1040 (1.9%) | 2980 (5.5%) | 2603 (4.8%) |
| kodim05-fs | 54464 | 5976 (11.0%) | 8592 (15.8%) | 12494 (22.9%) | 11274 (20.7%) |
| kodim05-none | 54464 | 974 (1.8%) | 2559 (4.7%) | 4158 (7.6%) | 3419 (6.3%) |
| kodim23-fs | 54464 | 5640 (10.4%) | 9259 (17.0%) | 13173 (24.2%) | 12213 (22.4%) |
| kodim23-none | 54464 | 51 (0.1%) | 913 (1.7%) | 1772 (3.3%) | 1624 (3.0%) |

The AFLI column equals the best any hires FLI picture can do: the two most common colours
of every 8x1 run. So v2i beats any AFLI picture on these images.

## spantypes.py: would X-expanded or multicolour sprites help?

```bash
python analysis/spantypes.py [SRC_DIR]
```

It runs the real converter and keeps its cell colour pairs. Then, for every line and
ignoring timing, it covers the pixels outside the cell pairs greedily with 8 sprites, one
sprite at a time, each taking the most new pixels. Four sets of sprite kinds are tried:

| kind | width | pixels | colours |
|---|---|---|---|
| `std` | 24 px | any pattern | one |
| `xexp` (`$d01d`) | 48 px | pairs | one |
| `mc` (`$d01c`) | 24 px | pairs | own, `$d025`, `$d026` |
| `mcx` (both) | 48 px | groups of 4 | as `mc` |

A pair or group is painted only where all its pixels have that colour. `$d025`/`$d026` are
shared by the whole line; the script tries every pair of the line's 6 most common leftover
colours. It takes about 15 minutes.

Columns of the results: `actual` is the converter's real result; `exact8` is the
converter's own exact cover without timing. The other four are greedy results per set of
sprite kinds.

Results (Nov 2026; the images are placed upper left here, which is why the dragon differs
from compare.py):

| image | actual | exact8 | std | +xexp | +mc | all | sprite kinds used (all) |
|---|---|---|---|---|---|---|---|
| dragon | 1798 | 1472 | 1480 | 1472 | 1325 | 1329 | std 1400, mc 115, xexp 38, mcx 16 |
| kodim01-fs | 6576 | 5541 | 5600 | 5600 | 5598 | 5598 | std 1457, mc 2, xexp 1 |
| kodim01-none | 135 | 52 | 53 | 60 | 51 | 57 | std 748, xexp 36, mc 2, mcx 1 |
| kodim05-fs | 6011 | 5283 | 5332 | 5323 | 5314 | 5309 | std 1439, xexp 14, mc 9, mcx 1 |
| kodim05-none | 936 | 754 | 758 | 763 | 675 | 695 | std 1185, xexp 82, mc 64, mcx 9 |
| kodim23-fs | 5652 | 4964 | 5016 | 5016 | 5013 | 5013 | std 1465, mc 3 |
| kodim23-none | 47 | 20 | 20 | 21 | 18 | 18 | std 765, xexp 18, mc 4 |

The greedy result with standard spans only is within about 1% of the exact cover, so the
comparison is fair. The sets with more kinds can come out worse than smaller ones
(kodim01-none, `all` vs `std`): the greedy is not exact.

Conclusions:

- **Multicolour:** about 10% fewer leftover pixels on flat images, nothing on F-S photos.
- **X-expanded:** nothing anywhere.
- **Neither is worth building.** Both figures are upper bounds that ignore the extra
  register writes.
- **Timing costs more.** The gap between `actual` and `exact8` is 688-1035 pixels on the
  F-S photos.

## timingloss.py: where do pixels go to timing?

```bash
python analysis/timingloss.py [SRC_DIR] > build/analysis/timingloss.md
```

It needs only the build's requirements. It runs the real converter (PAL, upper left, as
spantypes.py does) with `fit_line`, `do_row` and `recover` wrapped. For every line of the
chosen schedule it records:

- the pixels the exact 8-span cover leaves
- the pixels of the spans `fit_line` dropped
- the pixels `recover` still painted
- the writes the full span set asked for
- a probe: the first write that missed with no span dropped. The probe is undone, task ids
  included, so the result is the same as a plain conversion. It asserts that per line.

It prints a breakdown per image and then this summary. It takes about 6.5 minutes.

Results (Nov 2026):

| image | wrong | cover | dropped | recovered | lines dropping | writes/line |
|---|---|---|---|---|---|---|
| dragon | 1798 | 1472 | 401 | 75 | 65 | 5.1 |
| kodim01-fs | 6576 | 5541 | 1303 | 268 | 118 | 8.6 |
| kodim01-none | 135 | 52 | 86 | 3 | 19 | 1.5 |
| kodim05-fs | 6011 | 5283 | 973 | 245 | 88 | 7.8 |
| kodim05-none | 936 | 754 | 204 | 22 | 40 | 4.0 |
| kodim23-fs | 5652 | 4964 | 961 | 273 | 86 | 7.5 |
| kodim23-none | 47 | 20 | 28 | 1 | 13 | 1.4 |

`wrong` = `cover` + `dropped` - `recovered`. `recover` also saves some pixels the 8-span
limit left, not only dropped ones.

Dropped pixels by cause:

| image | missed X write first | pointer | badlines (12.5% of lines) | lines asking 9+ writes |
|---|---|---|---|---|
| dragon | 71% | 13% | 58% | 54% |
| kodim01-fs | 68% | 19% | 37% | 91% |
| kodim01-none | 59% | 10% | 60% | 21% |
| kodim05-fs | 76% | 16% | 49% | 80% |
| kodim05-none | 50% | 46% | 53% | 51% |
| kodim23-fs | 68% | 18% | 43% | 75% |
| kodim23-none | 93% | 4% | 54% | 11% |

The X column includes X writes of the previous line that the new writes pushed out. The
image starts at raster `$33`, so the badline is the first line of every character row;
its writes must land in the line before. The line before the badline loses almost
nothing.

Conclusions:

- **Two causes dominate:** X writes, and badlines. Badlines are 1 line in 8 but lose 37-60%
  of the dropped pixels.
- **The F-S photos run at capacity.** They ask for 7.5-8.6 writes a line on average, and
  their lines asking 9 or more lose most.
- **Pointer writes matter on some images:** 46% of the drops on kodim05-none. Which
  lines those misses fall on was not counted.

## badline_weight.py: dearer retasks into the badline

```bash
python analysis/badline_weight.py WEIGHT [IMAGE ...]
```

It replaces `row_cost` so that a sprite retask into a character row's badline costs
WEIGHT instead of 20, then converts every image (PAL, upper left). The default images are
`build/analysis/src` and `input/*.png`. The five weights ran in parallel in about 10
minutes. Wrong pixels (Nov 2026):

| image | 20 (before) | 40 | 60 | 100 | 200 |
|---|---|---|---|---|---|
| dragon (296) | 1798 | 1811 | 1795 | 1723 | 1766 |
| kodim01-fs | 6576 | 6536 | 6521 | 6491 | 6469 |
| kodim01-none | 135 | 123 | 118 | 104 | 84 |
| kodim05-fs | 6011 | 6009 | 6012 | 5904 | 5916 |
| kodim05-none | 936 | 936 | 937 | 925 | 975 |
| kodim23-fs | 5652 | 5665 | 5596 | 5603 | 5547 |
| kodim23-none | 47 | 31 | 32 | 33 | 44 |
| castle | 309 | 302 | 303 | 305 | 319 |
| dragon (320) | 2064 | 2081 | 2078 | 2021 | 1981 |
| gaoler | 309 | 309 | 312 | 316 | 304 |
| princess | 260 | 258 | 253 | 257 | 279 |
| total | 24097 | 24061 | 23957 | 23682 | 23684 |

At 100, the total falls by 1.7% (415 pixels, about 10% of the timing loss). 10 of 11 images
are better; gaoler is 7 pixels worse. 200 has the same total but swings more both ways.
`convert.py` now uses 100 (`RETASK`).

## dither_score.py: img2c64 settings, wrong pixels and error against the photo

```bash
python analysis/dither_score.py SETTING [PHOTO ...]
```

It needs only the build's requirements. The default photos are kodim01, 03, 05, 15 and 23
from `images/kodak-full/`. A setting is `MODE[:K][,c=S][,l=N]`, which are img2c64's `-d`,
`-c` and `-l`; for example, `hybrid:90,c=0.6,l=6`.

For every photo, img2c64 makes the PAL picture (320 wide) and the converter converts it
(upper left). The script reports:

- `wrong`: the pixels the converter gets wrong.
- `rms dith`: the 3x3-blurred RMS error (RGB, 0-255) of img2c64's picture against the photo,
  resized as img2c64 resizes it.
- `rms c64`: the same for what the C64 shows.

What the C64 shows is saved as `build/analysis/dither/<photo>_<setting>.png`. A setting
takes a few seconds per photo, so run settings in parallel, one process each.

Results (Nov 2026), the means over the five photos:

| setting | wrong | rms dith | rms c64 |
|---|---|---|---|
| fs | 6365 (9.9%) | 9.10 | 13.59 |
| none | 315 (0.5%) | 21.85 | 22.02 |
| hybrid:90 | 801 (1.3%) | 13.84 | 14.46 |
| hybrid:90,l=8 | 377 (0.6%) | 14.45 | 14.72 |
| hybrid:90,l=6 | 165 (0.3%) | 14.77 | 14.89 |
| hybrid:90,l=4 | 52 (0.1%) | 15.21 | 15.24 |
| hybrid:60,l=6 | 422 (0.7%) | 14.57 | 14.81 |
| hybrid:40,l=6 | 428 (0.7%) | 14.60 | 14.84 |
| hybrid:90,c=0.6 | 484 (0.8%) | 18.32 | 18.64 |
| hybrid:90,c=0.6,l=6 | 119 (0.2%) | 18.80 | 18.89 |
| hybrid:60,c=0.6,l=6 | 551 (0.9%) | 18.26 | 18.55 |

Conclusions:

- **The budget (`-l`, two colours a cell plus at most N runs of 24 px a line)** does what
  it should: wrong pixels drop to a half (`l=8`) or a fifth (`l=6`) of hybrid's.
- **It doesn't bring the screen closer to the photo.** `rms c64` rises a little (14.46 ->
  14.72 -> 14.89): hybrid's wrong pixels fall back to a near colour anyway, and the budget
  gives up colours a converted hybrid picture would have shown.
- **What it buys is predictability:** the C64 shows almost exactly img2c64's picture.
- **A lower escape distance `E` with the budget** brings more wrong pixels and no better
  RMS.
- **By this measure F-S still shows the closest picture** (13.59), despite 10% wrong pixels:
  the blur hides its stray pixels.
- **`-c 0.6` scores far worse,** because it moves colours on purpose (warmer, more saturated
  looking). RMS against the photo can't judge that; the eye has to.
