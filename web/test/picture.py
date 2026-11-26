"""A picture as tools/img2c64.py loads it (orientation, colour profile, alpha), as JSON for
web/test/prg_e2e.mjs, which runs the page's pipeline on exactly those pixels.

    python3 web/test/picture.py photo.jpg out.json
"""

import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import img2c64  # noqa: E402


def main(src, out):
    img = img2c64.load(src)
    with open(out, "w") as f:
        json.dump(dict(width=img.width, height=img.height,
                       rgb=base64.b64encode(img.tobytes()).decode()), f)


if __name__ == "__main__":
    main(*sys.argv[1:])
