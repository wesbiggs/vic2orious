"""Assembles the dual demo with two .v2i (the build's, with their load address) as
vic2.prg does, for web/test/prg_golden.mjs.

    python3 web/test/prg_golden.py build/pal/princess.v2i build/ntsc/princess.v2i out.prg
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import prg_template  # noqa: E402

if __name__ == "__main__":
    pal, ntsc = (open(p, "rb").read()[2:] for p in sys.argv[1:3])
    with open(sys.argv[3], "wb") as f:
        f.write(prg_template.assemble(pal, ntsc))
