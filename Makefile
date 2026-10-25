# Copyright 2026 Wes Biggs. Licensed under the Apache License, Version 2.0 (LICENSE).
#
# vic2orious: shortcuts for python3 -m vic2.build and for running the results in VICE.
# Run "make help" for the targets and options.

PYTHON  ?= python3
X64     ?= x64sc
VICE    := $(X64) -pal -VICIIextpal -VICIIpalette pepto-pal.vpl

# options (make FRAME=1 AT=2,3 run)
IMAGES  ?=                      # input files to build (default: all of input/*.png)
FRAME   ?=                      # 1: frame the images (build -b)
AT      ?=                      # COLUMN,ROW: place the images there (build --at)
LEADING ?=                      # pixel lines between text lines (default 2)
AUTO    ?=                      # frames per slideshow image (default 250, 0: until space)
HOLD    ?=                      # seconds per diskshow image (default 15, 0: until space)
DISK    ?=                      # d64 or d81 (default: d64 if everything fits, else d81)
IMAGE   ?=                      # run-viewer: image name to type at the prompt
ASK     ?= princess             # run-ask: which ask-<name>.prg

# options that change the conversion, and all of them
COPTS := $(strip $(if $(strip $(FRAME)),-b) $(if $(strip $(AT)),--at $(strip $(AT))) \
         $(if $(strip $(LEADING)),--leading $(strip $(LEADING))))
OPTS  := $(strip $(COPTS) $(if $(strip $(AUTO)),--auto $(strip $(AUTO))) \
         $(if $(strip $(HOLD)),--hold $(strip $(HOLD))) \
         $(if $(strip $(DISK)),--disk $(strip $(DISK))) $(IMAGES))

PNGS    := $(or $(strip $(IMAGES)),$(wildcard input/*.png))
JSONS   := $(foreach p,$(PNGS),build/$(basename $(notdir $(p))).json)
SOURCES := $(wildcard input/* vic2/*.py asm/*)
STAMP   := build/.built

# the disk the build made (.d64 or .d81) and the drive VICE needs for it
DISKIMG  = $$(ls build/vic2orious.d81 2>/dev/null || echo build/vic2orious.d64)
DRIVE    = $$(test -e build/vic2orious.d81 && echo -drive8type 1581)

.PHONY: all build convert verify run run-slideshow run-diskshow run-viewer run-ask run-v2i \
        run-v2t run-d64 clean help FORCE

all: build

build: $(STAMP)

# step 1: convert each image on its own (build/<name>.json records the result; make -j
# converts several at once). The build skips images whose result is still valid, so
# touching vic2/*.py only reconverts when a converter source really changed.
convert: $(JSONS)

$(foreach p,$(PNGS),$(eval build/$(basename $(notdir $(p))).json: $(p) $(wildcard $(basename $(p)).txt)))

$(JSONS): $(wildcard vic2/*.py) build/.copts
	$(PYTHON) -m vic2.build --convert-only $(COPTS) $(filter %.png,$^)

# step 2: programs and disk from the converted images (stamped, as make 3.81 has no
# grouped targets); reruns when sources or options change
$(STAMP): $(JSONS) $(SOURCES) build/.opts
	$(PYTHON) -m vic2.build $(OPTS)
	@touch $@

build/.opts build/.copts: FORCE
	@mkdir -p build
	@echo '$(if $(filter %.copts,$@),$(COPTS),$(OPTS))' | cmp -s - $@ || \
		echo '$(if $(filter %.copts,$@),$(COPTS),$(OPTS))' > $@

verify: build/.opts
	$(PYTHON) -m vic2.build --verify $(OPTS)
	@touch $(STAMP)

run: run-slideshow

run-slideshow: build
	$(VICE) -autostartprgmode 1 build/slideshow.prg

run-diskshow: build
	$(VICE) $(DRIVE) -8 $(DISKIMG) -autostart build/diskshow.prg

run-viewer: build
	$(VICE) $(DRIVE) -8 $(DISKIMG) -autostart build/viewer.prg \
		$(if $(strip $(IMAGE)),-keybuf '$(strip $(IMAGE))\n')

run-ask: build
	$(VICE) -autostartprgmode 1 build/ask-$(strip $(ASK)).prg

run-v2i: build
	$(VICE) -autostartprgmode 1 build/v2i-demo.prg

run-v2t: build
	$(VICE) -autostartprgmode 1 build/v2t-demo.prg

run-d64: build
	$(VICE) $(DRIVE) -autostart $(DISKIMG)

clean:
	rm -rf build

help:
	@echo "make [build]        convert input/ and assemble everything into build/ (-j8: in parallel)"
	@echo "make convert        only convert the images that changed (build/<name>.v2i)"
	@echo "make verify         build and compare every image (and ask demo) with VICE"
	@echo "make run            build and run the slideshow (same as run-slideshow; holds"
	@echo "                    as many images as fit in one PRG)"
	@echo "make run-diskshow   run the disk slideshow (loads every image from disk in turn)"
	@echo "make run-viewer     run the disk viewer; IMAGE=princess types the name for you"
	@echo "make run-ask        run the ask demo (ASK=princess)"
	@echo "make run-v2i        run the v2i-only demo (one image, space returns to BASIC)"
	@echo "make run-v2t        run the v2t-only demo (text, KERNAL on, any key returns)"
	@echo "make run-d64        boot the disk (.d64, or .d81 when the images need it)"
	@echo "make clean          remove build/"
	@echo "options: IMAGES='input/a.png ...' FRAME=1 AT=COLUMN,ROW LEADING=n AUTO=n HOLD=n DISK=d64|d81"
