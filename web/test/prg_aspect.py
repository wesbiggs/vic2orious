# For web/test/prg_e2e.mjs --aspect none.
# vic2.prg with img2c64 run with -a none (the picture's pixels as they are, one PNG for
# both systems), which vic2.prg has no option for:
#   python3 web/test/prg_aspect.py [vic2.prg's arguments]
import os
import subprocess
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from vic2 import prg
orig = subprocess.run


def run(cmd, *args, **kw):
    if len(cmd) > 1 and cmd[1] == prg.TOOL:
        cmd = cmd[:2] + ["-a", "none"] + cmd[2:]
    return orig(cmd, *args, **kw)


subprocess.run = run
sys.argv[0] = "vic2.prg"
sys.exit(prg.main())
