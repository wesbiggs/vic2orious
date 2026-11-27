"""The converter and img2c64's picture work, done by the JavaScript the web page runs
(web/js), through tools/engine.mjs in Node: one engine for the page and the Python tools.

Also what the Python side still needs of the old engine: the video system the build is
for (set_standard, STANDARD, SYSTEM_ID) and the image's place on the screen (Geometry).
Needs Node 18 or later ($NODE, else node on the PATH); no npm packages.
"""

import base64
import glob
import json
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "tools", "engine.mjs")
# the files a conversion depends on (the build's cache key hashes them)
SOURCES = sorted(glob.glob(os.path.join(ROOT, "web", "js", "*.js"))) + [CLI]

STANDARD = "pal"
SYSTEM_ID = {"pal": 0, "ntsc": 1}       # .v2i header byte 24
MAX_W, MAX_H = 320, 200


def set_standard(standard):
    """The video system the build converts for ("pal" or "ntsc"), for the whole process."""
    global STANDARD
    if standard not in SYSTEM_ID:
        raise ValueError("unknown video standard %r" % standard)
    STANDARD = standard


class Geometry:
    """An image's size and its place on the screen, in whole characters (the converter's
    Geometry, web/js/convert.js, without the sprite arithmetic). w is in image pixels:
    wide pixels for multicolour (mc), each scale = 2 screen pixels, cells cw = 4 wide."""

    def __init__(self, w, h, frame=False, at=None, mc=False):
        self.mc = mc
        self.scale = 2 if mc else 1
        self.cw = 8 // self.scale
        self.w, self.h = w, h
        self.w_px = w * self.scale
        self.cols, self.rows = w // self.cw, h // 8
        self.col0, self.row0 = at if at is not None else ((1, 1) if frame else (0, 0))
        self.frame = frame
        self.raster0 = 0x33 + 8 * self.row0     # first raster line of the image

    @staticmethod
    def frame_fits(col0, row0, cols, rows):
        """The frame needs the ring of cells around the image."""
        return col0 >= 1 and row0 >= 1 and col0 + cols <= 39 and row0 + rows <= 24


class EngineError(Exception):
    pass


def node():
    exe = os.environ.get("NODE") or shutil.which("node")
    if not exe:
        raise SystemExit("vic2: needs Node 18 or later (https://nodejs.org; or set NODE): the "
                         "converter is the JavaScript in web/js")
    return exe


def run(request, log=print, on_result=None):
    """Send request to tools/engine.mjs; log its log lines as they come. Returns the
    results (on_result is called with each as it arrives, too). Raises EngineError."""
    p = subprocess.Popen([node(), CLI], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         text=True, encoding="utf-8")
    try:
        p.stdin.write(json.dumps(request))
        p.stdin.close()
        results, error = [], None
        for line in p.stdout:
            m = json.loads(line)
            if "log" in m:
                log(m["log"])
            elif "result" in m:
                results.append(m["result"])
                if on_result:
                    on_result(m["result"])
            elif "error" in m:
                error = m["error"]
    finally:
        rc = p.wait()
    if error or rc:
        raise EngineError(error or "tools/engine.mjs exited with status %d" % rc)
    return results


def b64(data):
    return base64.b64encode(bytes(data)).decode("ascii")


def unb64(text):
    return base64.b64decode(text)


def rows_of(data, w, h):
    return [list(data[y * w:(y + 1) * w]) for y in range(h)]


class Layers:
    """What vic2/layers.py draws of a conversion, as the converter left it."""

    def __init__(self, g, d):
        self.g = g
        w, h = g.w, g.h
        self.pairs = [[tuple(p) for p in row] for row in d["pairs"]]
        self._bits = rows_of(unb64(d["bitmap"]), w, h)
        self._cover = [[None if v == 255 else v for v in row]
                       for row in rows_of(unb64(d["cover"]), w, h)]
        self.sdata = [{r: bits for r, bits in s} for s in d["sdata"]]
        self.line_cfg = [{r: tuple(cfg) for r, cfg in s} for s in d["line_cfg"]]
        self.bad_lines = set(d["bad_lines"])

    def bitmap(self):
        return self._bits

    def sprite_cover(self):
        return self._cover


def convert(img, v2i, frame, at, mc, settings, image_name, palette_name, thumb, picture,
            thumb_palette, log=print, layers=True):
    """Convert img (rows of palette indices; multicolour: wide pixels) for STANDARD at
    at = (column, row), framed if frame, and write the .v2i to v2i (with img2c64's
    settings text, its thumbnail bytes thumb or one made of picture, an RGB Pillow image
    in thumb_palette's colours). Returns a dict: w, h, geom, rendered (rows as the C64
    shows them), wrong_px, bad_lines, top_slot, size, thumb (bytes), layers (Layers)."""
    h, w = len(img), len(img[0])
    q = dict(cmd="convert", system=STANDARD, w=w, h=h, rows=b64(v for row in img for v in row),
             mc=mc, frame=frame, at=list(at), settings=settings, imageName=image_name,
             paletteName=palette_name, v2i=os.path.abspath(v2i), layers=layers,
             thumb=thumb.hex() if thumb else None)
    if not thumb:
        q.update(picture=dict(w=picture.width, h=picture.height,
                              rgb=b64(picture.convert("RGB").tobytes())),
                 thumbPalette=[list(c) for c in thumb_palette])
    (r,) = run(q, log=log)
    g = Geometry(w, h, frame=r["frame"], at=tuple(r["at"]), mc=mc)
    r.update(geom=g, rendered=rows_of(unb64(r["rendered"]), w, h),
             thumb=bytes.fromhex(r["thumb"]))
    if layers:
        r["layers"] = Layers(g, r["layers"])
    return r


def img2c64(jobs, images, options, log=print, on_result=None):
    """tools/img2c64.py's work: jobs (src, base, label, system, index into images), images
    (RGB Pillow images, as img2c64 loaded them), options (dither, runs, weights, top,
    chroma, view, viewName, mc, frame, box). on_result(job, w, h, indices, settings,
    thumb bytes, colours, note) is called for each output as it is ready, in the jobs'
    order; colours: the 16 (r, g, b) to write it in."""
    q = dict(options, cmd="img2c64",
             jobs=[dict(src=s, base=b, label=l, system=sy, image=i) for s, b, l, sy, i in jobs],
             images=[dict(w=im.width, h=im.height, rgb=b64(im.tobytes())) for im in images])

    def got(r):
        on_result(r["job"], r["w"], r["h"], unb64(r["idx"]), r["settings"],
                  bytes.fromhex(r["thumb"]), [tuple(c) for c in r["palette"]], r["note"])
    run(q, log=log, on_result=got)
