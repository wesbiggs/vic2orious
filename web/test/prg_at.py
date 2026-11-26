# For web/test/prg_e2e.mjs --at.
# vic2.prg with its conversions placed at COLUMN,ROW, as vic2.build --at places them:
#   python3 web/test/prg_at.py COLUMN,ROW [vic2.prg's arguments]
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from vic2 import build, prg
at = tuple(int(v) for v in sys.argv.pop(1).split(","))
orig = build.convert_image
build.convert_image = lambda path, **kw: orig(path, **dict(kw, at=at, force=True))
sys.argv[0] = "vic2.prg"
sys.exit(prg.main())
