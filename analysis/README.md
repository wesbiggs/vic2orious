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
from `images/kodak-full/`. A setting is `MODE[:K][,c=S][,l=N|none]`, which are img2c64's `-d`,
`-c` and `-l`; for example, `hybrid:90,c=0.6,l=6`.

For every photo, img2c64 makes the PAL picture (320 wide) and the converter converts it
(upper left). The script reports:

- `wrong`: the pixels the converter gets wrong.
- `rms dith`: the 3x3-blurred RMS error (RGB, 0-255) of img2c64's picture against the photo,
  resized as img2c64 resizes it.
- `rms c64`: the same for what the C64 shows.

What the C64 shows is saved as `build/analysis/dither/<photo>_<setting>.png`. A setting
takes a few seconds per photo, so run settings in parallel, one process each.

Results (Nov 2026), the means over the five photos. These were measured with hybrid's
old defaults (spread 0.25, clamp 32, no budget unless `l=` is given); see below for the
current ones:

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

The parrots' green background goes grey under hybrid, for two reasons:

- **Pair choice:** `cell_pairs` adds `HYBRID_SPREAD` (0.25) times the cost of mixing
  far-apart colours, so it picks grey pairs over grey/green ones.
- **Error clamp:** the carried error is clamped to ±`HYBRID_CLAMP` (32), so green error
  rarely builds up enough to escape the pair.

Loosening both, with the line budget (`spread=` and `clamp=` replace the two constants):

| setting | wrong | rms dith | rms c64 |
|---|---|---|---|
| hybrid:90,l=8 | 377 (0.6%) | 14.45 | 14.72 |
| hybrid:90,l=8,spread=0.1 | 413 (0.6%) | 14.20 | 14.45 |
| hybrid:90,l=8,spread=0 | 1332 (2.1%) | 17.23 | 17.99 |
| hybrid:90,l=8,clamp=64 | 1485 (2.3%) | 13.04 | 13.83 |
| hybrid:90,l=8,clamp=none | 2099 (3.3%) | 14.00 | 14.79 |
| hybrid:90,l=8,spread=0.1,clamp=64 | 1519 (2.4%) | 12.27 | 13.09 |
| hybrid:90,l=6,spread=0.1 | 176 (0.3%) | 14.47 | 14.58 |
| hybrid:90,l=6,clamp=64 | 706 (1.1%) | 13.79 | 14.18 |
| hybrid:90,l=6,spread=0.1,clamp=64 | 803 (1.3%) | 12.87 | 13.28 |
| hybrid:90,spread=0.1,clamp=64 | 4198 (6.6%) | 9.73 | 12.87 |

- **`spread=0.1,clamp=64` with `-l 6` or `-l 8`** shows a picture closer to the photo than
  F-S does (13.28 / 13.09 against 13.59), with a quarter or less of its wrong pixels. The
  wrong pixels are as many as plain hybrid:90's at `-l 6`, 2.4% at `-l 8`.
- **On kodim23, the parrots:** 17.09 -> 14.33. Most of the green background comes back.
  At `-l 6` some 8x8 cells show as blocks of green.
- **Spread 0 picks pairs too far apart,** and no clamp diffuses too much colour; both are
  worse.

`spread=0.1,clamp=64,l=8` is hybrid's default since (img2c64 `HYBRID_SPREAD`,
`HYBRID_CLAMP`, `HYBRID_RUNS`); a setting without `l=` now gets `l=8`, `l=none` turns the
budget off, and the old hybrid is `hybrid:90,l=none,spread=0.25,clamp=32`. The new defaults
give the numbers above (2.4%, 13.09). On IMG_1639 (320x200 PAL, a hard one: stone, sky,
foliage):

| setting | wrong | rms dith | rms c64 |
|---|---|---|---|
| fs | 7875 (14.6%) | 7.74 | 14.05 |
| old hybrid:90 | 1790 (3.3%) | 12.98 | 14.61 |
| old hybrid:90,l=8 | 724 (1.3%) | 14.77 | 15.44 |
| hybrid:90 (new default) | 1667 (3.1%) | 13.42 | 14.53 |
| hybrid:90,l=6 | 838 (1.6%) | 13.85 | 14.38 |
| hybrid:90,l=none | 6100 (11.3%) | 8.48 | 13.33 |
| hybrid:90,c=0.6 | 1543 (2.9%) | 17.66 | 18.46 |

- **The new default beats the old hybrid here too,** slightly (14.53 against 14.61, fewer
  wrong pixels), and the old one with `-l 8` clearly (15.44).
- **F-S stays closer by RMS on this one** (14.05), and `-l none` closer still (13.33) at
  11% wrong. `-l 6` is the best of the budgeted settings here.

## dither_rank.py: one picture, settings ranked by weighted RMS, SSIM and colour error

```bash
python analysis/dither_rank.py PHOTO [-w RMS,SSIM,COLOR] [-s SETTING ...] [--blur] [--ntsc] [-j N]
```

Runs each setting (written as for `dither_score.py`; default: none, fs, fs:0.75, fs:0.5,
atkinson, atkinson:0.75, hybrid, hybrid,l=6, hybrid,l=none) through img2c64 and the
converter, one process per setting, and scores what the C64 shows against the resized
photo:

- `rms`: the 3x3-blurred RMS error, as `rms c64` above. Lower is better.
- `ssim`: mean SSIM of the luma (11x11 Gaussian window, sigma 1.5), unblurred; with
  `--blur`, of the blurred pictures, so dither noise counts as little as it does in `rms`.
- `color`: the mean distance of the blurred pictures in CIELAB's a*b* plane (chroma and
  hue, not lightness). Lower is better.

Each metric is scaled over the settings of the run (best 1, worst 0), and `score` is
their weighted mean: `-w 1,2,1` counts SSIM twice, `-w 0,1,1` ignores RMS (the default).
The scores are relative to the settings tried, so adding one can reorder the others.
Pictures go to `build/analysis/rank/`.

There was a PSNR too, dropped as redundant: blurred, it is `rms` on a log scale (20
log10(255 / rms)); unblurred, it ranked the settings as unblurred SSIM does (rank
correlation 0.98 on kodim12, 1.00 on kodim23), and as blurred SSIM does on kodim12.

The tables below were measured before `color` existed. kodim23 (the parrots), PAL, `-w 1,2`:

| rank | setting | score | rms | ssim | wrong |
|---|---|---|---|---|---|
| 1 | none | 0.667 | 25.71 | 0.7228 | 71 (0.1%) |
| 2 | fs:0.5 | 0.560 | 16.75 | 0.4744 | 1328 (2.1%) |
| 3 | atkinson:0.75 | 0.555 | 16.37 | 0.4636 | 1486 (2.3%) |
| 4 | atkinson | 0.482 | 14.96 | 0.3862 | 2921 (4.6%) |
| 5 | fs:0.75 | 0.462 | 14.45 | 0.3628 | 3367 (5.3%) |
| 6 | hybrid,l=none | 0.364 | 14.33 | 0.2949 | 4675 (7.3%) |
| 7 | hybrid | 0.354 | 14.33 | 0.2882 | 1283 (2.0%) |
| 8 | hybrid,l=6 | 0.354 | 14.50 | 0.2915 | 591 (0.9%) |
| 9 | fs | 0.328 | 14.52 | 0.2740 | 6753 (10.6%) |

- **Unblurred SSIM counts dither noise as error,** so it ranks the opposite way from the
  blurred RMS: the less a setting dithers, the better it scores. With its weight at 2
  that decides the order, and `none` wins despite the worst RMS.
- **Weight towards RMS,** or use `--blur`, to rank by how the picture looks from a
  normal viewing distance.

The same with `--blur`:

| rank | setting | score | rms | ssim | wrong |
|---|---|---|---|---|---|
| 1 | atkinson:0.75 | 0.940 | 16.37 | 0.8299 | 1486 (2.3%) |
| 2 | atkinson | 0.868 | 14.96 | 0.8163 | 2921 (4.6%) |
| 3 | fs:0.5 | 0.829 | 16.75 | 0.8179 | 1328 (2.1%) |
| 4 | fs:0.75 | 0.795 | 14.45 | 0.8057 | 3367 (5.3%) |
| 5 | none | 0.534 | 25.71 | 0.8140 | 71 (0.1%) |
| 6 | hybrid,l=none | 0.494 | 14.33 | 0.7692 | 4675 (7.3%) |
| 7 | hybrid | 0.488 | 14.33 | 0.7685 | 1283 (2.0%) |
| 8 | hybrid,l=6 | 0.456 | 14.50 | 0.7652 | 591 (0.9%) |
| 9 | fs | 0.328 | 14.52 | 0.7499 | 6753 (10.6%) |

- **`none` drops to fifth:** its blurred SSIM is still high (flat areas keep their
  structure), but its RMS is by far the worst.
- **Blurred SSIM prefers the lighter error diffusion** (Atkinson, F-S at 0.5-0.75) over
  hybrid, whose pairs flatten detail inside cells.

kodim12 (people on a beach, one default F-S does badly), `-w 1,2 --blur`:

| rank | setting | score | rms | ssim | wrong |
|---|---|---|---|---|---|
| 1 | atkinson:0.75 | 0.825 | 14.67 | 0.8585 | 684 (1.1%) |
| 2 | fs:0.5 | 0.812 | 15.07 | 0.8588 | 651 (1.0%) |
| 3 | none | 0.667 | 20.45 | 0.8679 | 31 (0.0%) |
| 4 | atkinson | 0.666 | 12.54 | 0.8249 | 2397 (3.7%) |
| 5 | fs:0.75 | 0.561 | 12.52 | 0.8101 | 2945 (4.6%) |
| 6 | hybrid | 0.397 | 12.39 | 0.7868 | 2006 (3.1%) |
| 7 | hybrid,l=6 | 0.387 | 12.91 | 0.7882 | 1243 (1.9%) |
| 8 | hybrid,l=none | 0.369 | 11.95 | 0.7805 | 4714 (7.4%) |
| 9 | fs | 0.298 | 12.86 | 0.7756 | 6721 (10.5%) |

- **Default F-S comes last on SSIM** either way here, and fifth on RMS.

By eye, `-w 1,2 --blur` picked well on kodim12 (atkinson:0.75 looked best), less well on
the colourful ones: its winners on kodim23 (atkinson:0.75) and kodim05 (fs:0.5) are clean
but turn the parrots' green background and blue wing and the motorbikes' green and red
mostly grey or brown. SSIM only sees lightness, and a weak error diffusion never builds up
enough error to leave the nearest grey, so nothing charged for the lost colour.

- **SSIM on colour channels does not fix it.** On YCbCr (Y 0.8, Cb and Cr 0.1 each), and
  on a*b* with a shift-invariant mean term, it counts the dither's colour speckle as
  structure: Cb/Cr SSIM liked `none` best on all three photos.
- **A blurred colour error does** (`color`): `none` is worst on all three, full-strength
  diffusion best.

Winners (top three) with `color`, all `--blur`, against the picks by eye (kodim12
atkinson:0.75, then fs:0.5; kodim23 atkinson or fs:0.75; kodim05 fs:0.5 or fs:0.75):

| weights | kodim12 | kodim23 | kodim05 |
|---|---|---|---|
| 1,2,0 (no colour) | atkinson:0.75, fs:0.5, none | atkinson:0.75, atkinson, fs:0.5 | fs:0.5, fs:0.75, atkinson:0.75 |
| 1,2,1 | atkinson:0.75, fs:0.5, atkinson | atkinson:0.75 = atkinson, fs:0.75 | fs:0.75, fs:0.5, hybrid,l=none |
| 1,2,2 | atkinson, atkinson:0.75, fs:0.5 | atkinson, fs:0.75, atkinson:0.75 | fs:0.75, hybrid,l=none, atkinson |
| **0,1,1** | **atkinson:0.75**, fs:0.5, atkinson | **atkinson**, atkinson:0.75, fs:0.75 | **fs:0.75**, hybrid,l=none, atkinson |
| 1,1,1 | atkinson, fs:0.75, atkinson:0.75 | atkinson, fs:0.75, atkinson:0.75 | fs:0.75, hybrid,l=none, atkinson |

- **`0,1,1` (the default) picks the setting that looked best on all three.** `rms` adds
  little next to `color` (both charge lost colour) and with weight it pulls towards
  full-strength diffusion.
- **No single setting wins everywhere:** atkinson:0.75 for the beach (little colour, big
  flat areas), atkinson for the parrots, fs:0.75 for the motorbikes. Full F-S and the
  budgeted hybrids are never in a top three: their colour is good but the converter's
  dropped spans (F-S) or cell blocks (hybrid) cost them SSIM.
- Three photos and one pair of eyes; check the weights on more pictures before trusting
  them.

The metrics, `rank` and the default settings and weights live in `vic2/dither_pick.py`
since; img2c64 uses them to pick a dither when it is given no `-d`.


## mc_estimate.py: would a multicolour bitmap mode be better?

```bash
python analysis/mc_estimate.py [DITHER ...] [-- PHOTO ...]
```

Multicolour bitmap (160x200 wide pixels, 3 colours per 4x8 cell plus one background) with
X-expanded hires sprites, which are 24 wide pixel, single colour spans: the converter's span
model in wide pixel units. img2c64 (PAL, Colodore) makes both pictures at the same scale
(for multicolour from the photo squeezed to half width). Hires gets the real converter
(with timing); multicolour gets the same cell search with colour triples (from each
cell's 7 most common colours) and the best of the image's 3 most common backgrounds, and
`convert.cover` with **no timing**, so its numbers are an upper bound. Wrong pixels are vs
img2c64's picture; RMS is the 3x3-blurred RGB error of what the C64 shows (multicolour
doubled to 320 wide) against the photo. Pictures and `results.txt` in
`build/analysis/mc/`. About 20 minutes for the default photos (hires F-S is the slow part).

Results (Nov 2026, kodim01, 03, 05, 15, 23, means):

| dither | hires wrong | hires rms | mc wrong | mc rms |
|---|---|---|---|---|
| none | 315 (0.5%) | 22.02 | 0 (0.0%) | 22.57 |
| fs | 6365 (9.9%) | 13.59 | 13 (0.0%) | **12.42** |
| atkinson:0.75 | 1707 (2.7%) | 14.53 | 0 (0.0%) | 15.15 |

- **Multicolour is all but exact:** 0-49 wrong pixels per picture, even with full F-S.
  3+1 colours per cell leave few pixels for the sprites, and 8 spans of 24 wide pixels
  cover 192 of 160 columns. Timing will cost some of that (an X-expanded span is 6 cycles,
  so write windows shrink), but there is a lot of slack.
- **With full F-S it is the closest to the photo of anything measured:** 12.42 against
  13.59 for hires F-S and 13.09 for hires' default hybrid (dither_score, same photos).
  Hires F-S loses ~10% of its pixels to the converter; multicolour shows all of its dither.
- **Without dither, or with lighter dither, hires is a little closer** (0.4-1.0): there
  both modes show their picture almost exactly, and hires has twice the horizontal
  resolution.
- The blur hides lost resolution, so the RMS favours multicolour somewhat: judge by eye
  too. Hires keeps the sharper edges (wheels, text); multicolour has visibly wider dither
  dots and no flat grey fallback patches.
