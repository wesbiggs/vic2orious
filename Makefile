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
AUTO    ?=                      # frames per slideshow image (default 250)
IMAGE   ?=                      # run-viewer: image name to type at the prompt
ASK     ?= princess             # run-ask: which ask-<name>.prg

OPTS := $(strip $(if $(strip $(FRAME)),-b) $(if $(strip $(AT)),--at $(strip $(AT))) \
        $(if $(strip $(LEADING)),--leading $(strip $(LEADING))) \
        $(if $(strip $(AUTO)),--auto $(strip $(AUTO))) $(IMAGES))

SOURCES := $(wildcard input/* vic2/*.py asm/*)
STAMP   := build/.built

.PHONY: all build verify run run-slideshow run-viewer run-ask run-v2i run-v2t run-d64 clean help FORCE

all: build

build: $(STAMP)

# one build makes all outputs (stamped, as make 3.81 has no grouped targets); it reruns
# when sources or options change
$(STAMP): $(SOURCES) build/.opts
	$(PYTHON) -m vic2.build $(OPTS)
	@touch $@

build/.opts: FORCE
	@mkdir -p build
	@echo '$(OPTS)' | cmp -s - $@ || echo '$(OPTS)' > $@

verify: build/.opts
	$(PYTHON) -m vic2.build --verify $(OPTS)
	@touch $(STAMP)

run: run-slideshow

run-slideshow: build
	$(VICE) -autostartprgmode 1 build/slideshow.prg

run-viewer: build
	$(VICE) -8 build/vic2orious.d64 -autostart build/viewer.prg \
		$(if $(strip $(IMAGE)),-keybuf '$(strip $(IMAGE))\n')

run-ask: build
	$(VICE) -autostartprgmode 1 build/ask-$(strip $(ASK)).prg

run-v2i: build
	$(VICE) -autostartprgmode 1 build/v2i-demo.prg

run-v2t: build
	$(VICE) -autostartprgmode 1 build/v2t-demo.prg

run-d64: build
	$(VICE) -autostart build/vic2orious.d64

clean:
	rm -rf build

help:
	@echo "make [build]        convert input/ and assemble everything into build/"
	@echo "make verify         build and compare every image (and ask demo) with VICE"
	@echo "make run            build and run the slideshow (same as run-slideshow)"
	@echo "make run-viewer     run the disk viewer; IMAGE=princess types the name for you"
	@echo "make run-ask        run the ask demo (ASK=princess)"
	@echo "make run-v2i        run the v2i-only demo (one image, space returns to BASIC)"
	@echo "make run-v2t        run the v2t-only demo (text, KERNAL on, any key returns)"
	@echo "make run-d64        boot the disk (loads its first program, the viewer)"
	@echo "make clean          remove build/"
	@echo "options: IMAGES='input/a.png ...' FRAME=1 AT=COLUMN,ROW LEADING=n AUTO=n"
