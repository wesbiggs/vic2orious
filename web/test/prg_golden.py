"""Assembles the dual demo with two reference .v2i (web/test/v2i_golden.py JSON) as
vic2.prg does, for web/test/prg_golden.mjs.

    python3 web/test/prg_golden.py pal.json ntsc.json out.prg
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import prg_template  # noqa: E402

if __name__ == "__main__":
    pal, ntsc = (bytes.fromhex(json.load(open(p))["v2i"])[2:] for p in sys.argv[1:3])
    with open(sys.argv[3], "wb") as f:
        f.write(prg_template.assemble(pal, ntsc))
