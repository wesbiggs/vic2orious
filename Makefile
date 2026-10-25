# Copyright 2026 Wes Biggs. Licensed under the Apache License, Version 2.0 (LICENSE).
#
# vic2orious: shortcuts for python3 -m vic2.build and for running the results in VICE.
# Run "make help" for the targets and options.

PYTHON  ?= python3
X64     ?= x64sc

# options (make FRAME=1 AT=2,3 run)
IMAGES  ?=                      # input files to build (default: all of input/*.png)
FRAME   ?=                      # 1: frame the images (build -b)
AT      ?=                      # COLUMN,ROW: place the images there (build --at)
LEADING ?=                      # pixel lines between text lines (default 2)
AUTO    ?=                      # frames per slideshow image (default 250, 0: until space)
HOLD    ?=                      # seconds per diskshow image (default 15, 0: until space)
DISK    ?=                      # d64 or d81 (default: d64 if everything fits, else d81)
NTSC    ?=                      # 1: build for NTSC C64s, into build/ntsc/ (default: PAL,
                                #    into build/pal/);
                                #    with DUAL=1: run in NTSC VICE
DUAL    ?=                      # 1: build both, and a disk for both in build/dual/
FAST    ?=                      # 1: run-diskshow/-viewer/-d64 load instantly (no true drive
                                #    emulation; VICE handles the KERNAL's disk calls)
IMAGE   ?=                      # run-viewer: image name to type at the prompt
ASK     ?= princess             # run-ask: which ask-<name>.prg

# build directories: SYS for the programs with images in them (build/pal/, build/ntsc/),
# B for the disk with diskshow and viewer (build/dual/ with DUAL=1); VICE's video system
SYS  := build/$(if $(strip $(NTSC)),ntsc,pal)
B    := $(if $(strip $(DUAL)),build/dual,$(SYS))
VICE := $(X64) $(if $(strip $(NTSC)),-ntsc,-pal) -VICIIextpal -VICIIpalette pepto-pal.vpl

# options that change the conversion (per system), and all of them
CBASE      := $(strip $(if $(strip $(FRAME)),-b) $(if $(strip $(AT)),--at $(strip $(AT))) \
              $(if $(strip $(LEADING)),--leading $(strip $(LEADING))))
COPTS_pal  := $(CBASE)
COPTS_ntsc := $(strip --ntsc $(CBASE))
DIR_pal    := build/pal
DIR_ntsc   := build/ntsc
SYSTEMS    := $(if $(strip $(DUAL)),pal ntsc,$(if $(strip $(NTSC)),ntsc,pal))
OPTS  := $(strip $(if $(strip $(DUAL)),--dual $(CBASE),$(COPTS_$(SYSTEMS))) \
         $(if $(strip $(AUTO)),--auto $(strip $(AUTO))) \
         $(if $(strip $(HOLD)),--hold $(strip $(HOLD))) \
         $(if $(strip $(DISK)),--disk $(strip $(DISK))) $(IMAGES))

PNGS    := $(or $(strip $(IMAGES)),$(wildcard input/*.png))
jsons    = $(foreach p,$(PNGS),$(DIR_$(1))/$(basename $(notdir $(p))).json)
JSONS   := $(foreach s,$(SYSTEMS),$(call jsons,$(s)))
SOURCES := $(wildcard input/* vic2/*.py asm/*)
STAMP   := $(B)/.built

# the disk the build made (.d64 or .d81) and the drive VICE needs for it (FAST=1: no true
# drive emulation, VICE traps the KERNAL's serial bus calls instead)
DISKIMG  = $$(ls $(B)/vic2orious.d81 2>/dev/null || echo $(B)/vic2orious.d64)
DRIVE    = $$(test -e $(B)/vic2orious.d81 && echo -drive8type 1581) \
           $(if $(strip $(FAST)),+drive8truedrive -trapdevice8)

.PHONY: all build convert verify run run-slideshow run-diskshow run-viewer run-ask run-v2i \
        run-v2t run-d64 clean help FORCE

all: build

build: $(STAMP)

# step 1: convert each image on its own, for each system (build/pal/<name>.json and
# build/ntsc/<name>.json record the results; make -j converts several at once). The
# build skips images whose result is still valid, so touching vic2/*.py only reconverts
# when a converter source really changed.
convert: $(JSONS)

define system_rules
$(foreach p,$(PNGS),$(eval $(DIR_$(1))/$(basename $(notdir $(p))).json: $(p) $(wildcard $(basename $(p)).txt)))
$(call jsons,$(1)): $(wildcard vic2/*.py) $(DIR_$(1))/.copts
	$(PYTHON) -m vic2.build --convert-only $(COPTS_$(1)) $$(filter %.png,$$^)
endef
$(foreach s,pal ntsc,$(eval $(call system_rules,$(s))))

# step 2: programs and disk from the converted images (stamped, as make 3.81 has no
# grouped targets); reruns when sources or options change
$(STAMP): $(JSONS) $(SOURCES) $(B)/.opts
	$(PYTHON) -m vic2.build $(OPTS)
	@touch $@

stampval = $(if $(filter %.opts,$(1)),$(OPTS),$(if $(filter build/ntsc/%,$(1)),$(COPTS_ntsc),$(COPTS_pal)))
$(sort $(B)/.opts build/pal/.copts build/ntsc/.copts): FORCE
	@mkdir -p $(@D)
	@echo '$(call stampval,$@)' | cmp -s - $@ || echo '$(call stampval,$@)' > $@

verify: $(B)/.opts
	$(PYTHON) -m vic2.build --verify $(OPTS)
	@touch $(STAMP)

run: run-slideshow

run-slideshow: build
	$(VICE) -autostartprgmode 1 $(SYS)/slideshow.prg

run-diskshow: build
	$(VICE) $(DRIVE) -8 $(DISKIMG) -autostart $(B)/diskshow.prg

run-viewer: build
	$(VICE) $(DRIVE) -8 $(DISKIMG) -autostart $(B)/viewer.prg \
		$(if $(strip $(IMAGE)),-keybuf '$(strip $(IMAGE))\n')

run-ask: build
	$(VICE) -autostartprgmode 1 $(SYS)/ask-$(strip $(ASK)).prg

run-v2i: build
	$(VICE) -autostartprgmode 1 $(SYS)/v2i-demo.prg

run-v2t: build
	$(VICE) -autostartprgmode 1 $(SYS)/v2t-demo.prg

run-d64: build
	$(VICE) $(DRIVE) -autostart $(DISKIMG)

clean:
	rm -rf build

help:
	@echo "make [build]        convert input/ and assemble everything into build/pal/ (-j8: in parallel)"
	@echo "make convert        only convert the images that changed (build/pal/<name>.v2i)"
	@echo "make verify         build and compare every image (and ask demo) with VICE"
	@echo "make run            build and run the slideshow (same as run-slideshow; holds"
	@echo "                    as many images as fit in one PRG)"
	@echo "make run-diskshow   run the disk slideshow (loads every image from disk in turn)"
	@echo "make run-viewer     run the disk viewer; IMAGE=princess types the name for you"
	@echo "make run-ask        run the ask demo (ASK=princess)"
	@echo "make run-v2i        run the v2i-only demo (one image, space returns to BASIC)"
	@echo "make run-v2t        run the v2t-only demo (text, KERNAL on, any key returns)"
	@echo "make run-d64        boot the disk (.d64, or .d81 when the images need it)"
	@echo "make clean          remove build/ (PAL, NTSC and dual builds)"
	@echo "options: IMAGES='input/a.png ...' FRAME=1 AT=COLUMN,ROW LEADING=n AUTO=n HOLD=n DISK=d64|d81"
	@echo "         NTSC=1 (for NTSC C64s; build/ntsc/ instead of build/pal/, run targets use it too)"
	@echo "         DUAL=1 (PAL and NTSC, and build/dual/: one disk for both; the run targets"
	@echo "                 use it, in NTSC VICE with NTSC=1)"
	@echo "         FAST=1 (run targets using the disk: instant loading)"
