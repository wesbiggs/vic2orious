"""A local web interface: upload a picture, compare dithers and modes, convert, download.

usage: python3 -m vic2.web [--port N] [--host ADDR] [--workers N] [--no-browser]

Serves vic2/web.html on http://127.0.0.1:8064/ (and opens it in the browser). Everything
runs on this machine, in build/web/<job>/ (one job per uploaded picture):

  src/<file>               the upload as it was sent; source.png: it as img2c64 reads it
  q/<cid>/<stem>[-p|-n].png  one candidate: the picture quantised by img2c64 (one dither,
                           one system's aspect, hires or multicolour, chroma, palette,
                           size), with its settings and thumbnail as img2c64 writes them;
                           estimate.png: what the C64 would show by dither_pick.estimate
                           (hires; multicolour: the picture with its pixels doubled)
  c/<gid>/<pal|ntsc>/      a dither's candidates (gid: the options and the dither, cid
                           without the system) converted, each for its system
                           (build.convert_image, centred; aspect none: the one PNG for
                           both): <stem>.v2i, _expected.png, _compare.png, _sprites.png,
                           _thumb.png, .json, log.txt
  c/<gid>/<stem>.prg       the v2i demo with the converted image(s): DUAL=1 with PAL and
                           NTSC, as vic2.prg makes it
  job.json                 the job's state, so a job survives a restart of the server

The work runs in a process pool (the converter's module globals, timing.set_standard and
build.BUILD, are per process); assembly in a pool of one (cl65 leaves its objects in asm/).
Candidates are scored like img2c64 -t does (blurred RMS, SSIM, a*b* colour error against
the source, from the estimate); the page ranks them with dither_pick.rank's formula.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from concurrent.futures import ProcessPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, unquote

from . import VERSION, build

WEB = os.path.join(build.ROOT, "build", "web")
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web.html")
TOOL = os.path.join(build.ROOT, "tools", "img2c64.py")
MAX_UPLOAD = 64 << 20
SUFFIX = {"pal": "-p", "ntsc": "-n", None: ""}
PALETTES = {"tv": os.path.join(build.ROOT, "tools", "tv.vpl"), "none": None}

_tool = None


def img2c64():
    """tools/img2c64.py as a module (once per process)."""
    global _tool
    if _tool is None:
        spec = importlib.util.spec_from_file_location("img2c64", TOOL)
        _tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_tool)
    return _tool


def candidates():
    """The dithers the page offers: dither_pick.CANDIDATES as (setting, dither, runs)."""
    from . import dither_pick
    return [list(c) for c in dither_pick.CANDIDATES]


def parse_setting(s):
    """A dither as the page names it: "fs:0.6", "hybrid:60,l=6", "hybrid,l=none" ->
    (dither, runs). Raises ValueError."""
    t = img2c64()
    d, _, rest = s.strip().lower().partition(",")
    runs = t.HYBRID_RUNS
    if rest:
        m = re.fullmatch(r"l=(none|[0-8])", rest.strip())
        if not m or not d.startswith("hybrid"):
            raise ValueError("%s: only hybrid takes ,l=N (0-8 or none)" % s)
        runs = None if m.group(1) == "none" else int(m.group(1))
    try:
        t.parse_dither(d)
    except Exception as e:                       # argparse.ArgumentTypeError
        raise ValueError(str(e))
    return d, runs


# ---- work, run in the pool's processes ------------------------------------------------

def _guard(fn, *args):
    """Run fn; turns SystemExit (build's way of failing) into an exception the pool
    passes back, with the message only."""
    try:
        return fn(*args)
    except SystemExit as e:
        raise RuntimeError(str(e)) from None


def preview_task(d, src, stem, system, dither, runs, opts):
    """Quantise src with one dither into d (see the module docstring); returns its
    metrics. dither None: src is already a C64 PNG (img2c64's), taken as it is."""
    return _guard(_preview, d, src, stem, system, dither, runs, opts)


def _preview(d, src, stem, system, dither, runs, opts):
    from PIL import Image
    from . import dither_pick
    t = img2c64()
    t0 = time.process_time()
    os.makedirs(d, exist_ok=True)
    png = os.path.join(d, stem + SUFFIX[system] + ".png")
    mc = opts["mc"]
    vpl = PALETTES[opts["palette"]]
    view = t.load_vpl(vpl) if vpl else None
    if dither is None:
        shutil.copyfile(src, png)
        out = Image.open(png).convert("RGB")
        img = out.resize((out.width * (2 if mc else 1), out.height), Image.Resampling.NEAREST)
        ref = img
    else:
        img = t.load(src)
        dith = t.parse_dither(dither)
        size = tuple(opts["size"])
        out = t.convert(img, system, dith, False, size, opts["chroma"], runs, view, mc)
        t.save(out, png, t.settings(src, system, dith, False, size, opts["chroma"], runs,
                                    None, vpl and os.path.basename(vpl), mc),
               t.thumbnail(img, out, system, view, mc))
        ref = None
    if mc:
        c64, wrong = out.resize((2 * out.width, out.height), Image.Resampling.NEAREST), None
    else:
        c64, wrong = dither_pick.estimate(out, system, view)
    c64.save(os.path.join(d, "estimate.png"))
    if ref is None:
        ref = img.resize(c64.size, Image.Resampling.LANCZOS)
    r = dither_pick.scores(c64, ref)
    r.update(wrong=wrong, pixels=out.width * out.height, w=out.width, h=out.height,
             secs=round(time.process_time() - t0, 2))
    return r


def convert_task(d, base, system):
    """Convert candidate PNG base (its -p/-n file for system, else base itself) for
    system into d; returns the stats and file names the page shows."""
    return _guard(_convert, d, base, system)


def _convert(d, base, system):
    from . import timing
    timing.set_standard(system)
    build.BUILD = d
    os.makedirs(d, exist_ok=True)
    log_path = os.path.join(d, "log.txt")
    with open(log_path, "w") as log:
        def say(m):
            log.write(m + "\n")
            log.flush()
        t0 = time.time()
        inf = build.convert_image(base, log=say, centre=True)
        say("%.1f s" % (time.time() - t0))
    g = inf["geom"]
    name = inf["name"]
    screen_png(os.path.join(d, name + "_expected.png"), build.image_source(base),
               os.path.join(d, name + "_screen.png"))
    return dict(name=name, w=g.w_px, h=inf["h"], col0=g.col0, row0=g.row0, mc=g.mc,
                wrong_px=inf["wrong_px"], pixels=inf["w"] * inf["h"],
                bad_lines=len(inf["bad_lines"]), size=inf["size"],
                files={k: name + s for k, s in (
                    ("v2i", ".v2i"), ("expected", "_expected.png"), ("screen", "_screen.png"),
                    ("compare", "_compare.png"), ("sprites", "_sprites.png"),
                    ("thumb", "_thumb.png"))})


def screen_png(expected, src, out):
    """expected (the build's _expected.png, in Pepto colours) recoloured into the palette
    of src (the PNG that was converted: tools/tv.vpl, Colodore as VICE shows it, ...), so
    it compares with the quantised picture."""
    from PIL import Image
    from .palette import PEPTO, palette_of
    pal = palette_of([c for _, c in Image.open(src).convert("RGB").getcolors(1 << 24)])
    lut = {tuple(p): tuple(q) for p, q in zip(PEPTO, pal)}
    im = Image.open(expected).convert("RGB")
    im.putdata([lut.get(p, p) for p in im.getdata()])
    im.save(out)


def prg_task(d, v2is, out):
    """The v2i demo (asm/v2i-demo.s) with the .v2i files (system -> path) as out."""
    return _guard(_prg, d, v2is, out)


def _prg(d, v2is, out):
    build.BUILD = d
    if len(v2is) == 2:
        inc = 'demo_img: .incbin "%s", 2\ndemo_img_n: .incbin "%s", 2\n' % (
            v2is["pal"], v2is["ntsc"])
        defines = ["DUAL=1"]
    else:
        inc = 'demo_img: .incbin "%s", 2\n' % next(iter(v2is.values()))
        defines = []
    with open(os.path.join(d, "v2idemo.inc"), "w") as f:
        f.write("        .data\n" + inc)
    try:
        build.assemble(out, "v2i-demo.s", defines=defines)
    except build.Overflow:
        raise RuntimeError("the images do not fit in one PRG ($0801-$bfff): try a smaller "
                           "size, or one system")
    return dict(size=os.path.getsize(out), systems=sorted(v2is))


# ---- jobs ------------------------------------------------------------------------------

class Jobs:
    """The jobs (uploaded pictures) and their tasks, in memory and in job.json."""

    def __init__(self, workers):
        self.lock = threading.RLock()
        self.jobs = {}
        self.pool = ProcessPoolExecutor(max_workers=workers)
        self.asm = ProcessPoolExecutor(max_workers=1)

    def dir(self, jid):
        return os.path.join(WEB, jid)

    def get(self, jid):
        if not re.fullmatch(r"[0-9a-f]{12}", jid or ""):
            return None
        with self.lock:
            if jid not in self.jobs:
                try:
                    with open(os.path.join(self.dir(jid), "job.json")) as f:
                        job = json.load(f)
                except (OSError, ValueError):
                    return None
                for t in job["tasks"].values():      # interrupted by a restart
                    if t["state"] == "working":
                        t.update(state="error", error="the server stopped while working")
                self.jobs[jid] = job
            return self.jobs[jid]

    def save(self, job):
        with self.lock:
            tmp = os.path.join(self.dir(job["id"]), "job.json.tmp")
            with open(tmp, "w") as f:
                json.dump(job, f)
            os.replace(tmp, os.path.join(self.dir(job["id"]), "job.json"))

    def create(self, filename, data):
        t = img2c64()
        jid = uuid.uuid4().hex[:12]
        d = self.dir(jid)
        os.makedirs(os.path.join(d, "src"))
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(filename)) or "picture"
        src = os.path.join(d, "src", name)
        with open(src, "wb") as f:
            f.write(data)
        try:
            img = t.load(src)
        except Exception as e:
            shutil.rmtree(d)
            raise ValueError("%s: not a picture img2c64 can read (%s)"
                             % (filename, str(e).replace(src, name)))
        img.save(os.path.join(d, "source.png"))
        stem = re.sub(r"[^a-z0-9_-]+", "", os.path.splitext(name)[0].lower())[:24] or "picture"
        stem = re.sub(r"-[pn]$", "", stem) or "picture"
        job = dict(id=jid, name=filename, src=src, stem=stem, w=img.width, h=img.height,
                   created=time.time(), tasks={}, c64=c64_settings(src))
        with self.lock:
            self.jobs[jid] = job
            self.save(job)
        return job

    def _start(self, job, key, pool, fn, args, info, then=None):
        """Run fn(*args) as task key of job (unless it is already done or working)."""
        with self.lock:
            old = job["tasks"].get(key)
            if old and old["state"] in ("working", "done"):
                return old
            task = dict(info, key=key, state="working", started=time.time(), result=None,
                        error=None)
            job["tasks"][key] = task
            self.save(job)

        def done(f):
            with self.lock:
                try:
                    task["result"] = f.result()
                    task["state"] = "done"
                except Exception as e:
                    task["error"] = str(e) or type(e).__name__
                    task["state"] = "error"
                    if not isinstance(e, RuntimeError):
                        traceback.print_exception(e)
                task["ended"] = time.time()
                self.save(job)
            if then:
                then()
        pool.submit(fn, *args).add_done_callback(done)
        return task

    def preview(self, job, opts, settings):
        """Quantise job's picture with each dither setting, per system of opts' aspect."""
        systems = {"both": ["pal", "ntsc"], "pal": ["pal"], "ntsc": ["ntsc"],
                   "none": [None]}[opts["aspect"]]
        okey = hashlib.sha1(json.dumps(
            [opts[k] for k in ("mc", "chroma", "palette", "size")]).encode()).hexdigest()[:8]
        keys = []
        for s in settings:
            if s == "as uploaded":
                if not job["c64"]:
                    raise ValueError("the upload is not an img2c64 PNG")
                c = job["c64"]
                system, dither, runs = c["system"], None, None
                o = dict(opts, mc=c["mc"], size=[job["w"], job["h"]])
                cid = gid = "upload-%s" % (system or "none")
            else:
                dither, runs = parse_setting(s)
                if opts["mc"] and dither.startswith("hybrid"):
                    continue                        # hybrid dithers hires cells
                o = opts
            for system in ([system] if dither is None else systems):
                if dither is not None:
                    gid = "%s-%s" % (okey, re.sub(r"[^a-z0-9.]+", "_", s))
                    cid = "%s-%s-%s" % (okey, system or "none", re.sub(r"[^a-z0-9.]+", "_", s))
                d = os.path.join(self.dir(job["id"]), "q", cid)
                self._start(job, cid, self.pool, preview_task,
                            (d, job["src"], job["stem"], system, dither, runs, o),
                            dict(kind="preview", setting=s, system=system, mc=o["mc"], gid=gid,
                                 dither=dither, runs=runs, opts=o, okey=okey,
                                 png="q/%s/%s%s.png" % (cid, job["stem"], SUFFIX[system]),
                                 estimate="q/%s/estimate.png" % cid))
                keys.append(cid)
        return keys

    def convert(self, job, cid):
        """Convert candidate cid and its siblings (the same dither and options for the
        other system) each for its system (aspect none: the one PNG for PAL and NTSC),
        then assemble one PRG with them."""
        cand = job["tasks"].get(cid)
        if not cand or cand["kind"] != "preview" or cand["state"] != "done":
            raise ValueError("no finished candidate %s" % cid)
        gid = cand["gid"]
        sibs = sorted((t for t in job["tasks"].values() if t["kind"] == "preview"
                       and t.get("gid") == gid and t["state"] == "done"),
                      key=lambda t: t["system"] or "")
        targets = [(t["system"], t["key"]) for t in sibs if t["system"]]
        if any(not t["system"] for t in sibs):
            targets = [("pal", sibs[0]["key"]), ("ntsc", sibs[0]["key"])]
        cdir = os.path.join(self.dir(job["id"]), "c", gid)
        prg_key = gid + "/prg"
        keys = [gid + "/" + system for system, _ in targets]
        with self.lock:
            for k in keys + [prg_key]:
                if job["tasks"].get(k, {}).get("state") in ("error", "done"):
                    del job["tasks"][k]             # again, with what is there now

        def then():
            with self.lock:
                tasks = [job["tasks"].get(k) for k in keys]
                if any(t is None or t["state"] == "working" for t in tasks):
                    return
                v2is = {t["system"]: os.path.join(cdir, t["system"], t["result"]["files"]["v2i"])
                        for t in tasks if t["state"] == "done"}
            if v2is:
                out = os.path.join(cdir, job["stem"] + ".prg")
                self._start(job, prg_key, self.asm, prg_task, (cdir, v2is, out),
                            dict(kind="prg", gid=gid, cid=cid,
                                 file="c/%s/%s.prg" % (gid, job["stem"])))
        for (system, src), k in zip(targets, keys):
            base = os.path.join(self.dir(job["id"]), "q", src, job["stem"] + ".png")
            self._start(job, k, self.pool, convert_task,
                        (os.path.join(cdir, system), base, system),
                        dict(kind="convert", gid=gid, cid=src, system=system,
                             dir="c/%s/%s" % (gid, system)),
                        then)
        then()
        return keys + [prg_key]

    def view(self, job):
        """job for the page: tasks with the log of conversions still working."""
        with self.lock:
            out = json.loads(json.dumps(job))
        for t in out["tasks"].values():
            if t["kind"] == "convert":
                try:
                    with open(os.path.join(self.dir(job["id"]), t["dir"], "log.txt")) as f:
                        t["log"] = f.read()[-4000:]
                except OSError:
                    t["log"] = ""
        out.pop("src")
        return out


def c64_settings(path):
    """If path is an img2c64 PNG: {system, mc} from its settings, else None."""
    from PIL import Image
    try:
        text = getattr(Image.open(path), "text", {}).get(build.META_KEY)
    except Exception:
        return None
    if not text:
        return None
    s = dict((k.strip(), v.strip()) for k, _, v in
             (l.partition(":") for l in text.splitlines()))
    system = s.get("aspect", "none").split()[0]
    return dict(system=system if system in ("pal", "ntsc") else None,
                mc=s.get("mode") == build.MODE_MC, settings=text)


# ---- HTTP ------------------------------------------------------------------------------

def make_handler(jobs):
    has_vice = bool(shutil.which("x64sc"))

    class Handler(BaseHTTPRequestHandler):
        server_version = "vic2orious/" + VERSION

        def log_message(self, fmt, *args):
            if not self.path.startswith("/api/job/"):    # the page polls these
                sys.stderr.write("%s\n" % (fmt % args))

        def reply(self, code, body, ctype="application/json", extra=()):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache" if any(k == "ETag" for k, _ in extra)
                             else "no-store")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def fail(self, code, msg):
            self.reply(code, {"error": msg})

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_UPLOAD:
                raise ValueError("too big (at most %d MB)" % (MAX_UPLOAD >> 20))
            return self.rfile.read(n)

        def do_GET(self):
            u = urlparse(self.path)
            p = u.path
            if p in ("/", "/index.html"):
                with open(PAGE, "rb") as f:
                    return self.reply(200, f.read(), "text/html; charset=utf-8")
            if p == "/api/config":
                t = img2c64()
                return self.reply(200, dict(
                    version=VERSION, candidates=candidates(), vice=has_vice,
                    palettes=[["tv", "tools/tv.vpl (TV, default)"],
                              ["none", "Colodore as VICE shows it"]],
                    par=t.PAR, max=[t.MAX_W, t.MAX_H]))
            m = re.fullmatch(r"/api/job/([0-9a-f]+)", p)
            if m:
                job = jobs.get(m.group(1))
                return self.reply(200, jobs.view(job)) if job else self.fail(404, "no such job")
            if p == "/api/jobs":
                out = []
                if os.path.isdir(WEB):
                    for jid in sorted(os.listdir(WEB)):
                        job = jobs.get(jid)
                        if job:
                            out.append(dict(id=jid, name=job["name"], created=job["created"]))
                return self.reply(200, sorted(out, key=lambda j: -j["created"]))
            m = re.fullmatch(r"/files/([0-9a-f]{12})/(.+)", p)
            if m and jobs.get(m.group(1)):
                root = os.path.realpath(jobs.dir(m.group(1)))
                f = os.path.realpath(os.path.join(root, unquote(m.group(2))))
                if not f.startswith(root + os.sep) or not os.path.isfile(f):
                    return self.fail(404, "no such file")
                ctype = {".png": "image/png", ".json": "application/json",
                         ".txt": "text/plain; charset=utf-8"}.get(
                    os.path.splitext(f)[1].lower(), "application/octet-stream")
                st = os.stat(f)
                etag = '"%x-%x"' % (st.st_mtime_ns, st.st_size)
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return
                extra = [("ETag", etag)]
                if "dl" in parse_qs(u.query):
                    extra.append(("Content-Disposition",
                                  'attachment; filename="%s"' % os.path.basename(f)))
                with open(f, "rb") as fh:
                    return self.reply(200, fh.read(), ctype, extra)
            self.fail(404, "not found")

        def do_POST(self):
            p = urlparse(self.path).path
            try:
                if p == "/api/upload":
                    name = unquote(self.headers.get("X-Filename") or "picture")
                    data = self.body()
                    if not data:
                        raise ValueError("empty upload")
                    return self.reply(200, jobs.view(jobs.create(name, data)))
                req = json.loads(self.body() or b"{}")
                job = jobs.get(req.get("id"))
                if not job:
                    return self.fail(404, "no such job")
                if p == "/api/preview":
                    opts = check_opts(req.get("opts") or {})
                    keys = jobs.preview(job, opts, req.get("settings") or [])
                    return self.reply(200, dict(keys=keys))
                if p == "/api/convert":
                    return self.reply(200, dict(keys=jobs.convert(job, req.get("cid"))))
                if p == "/api/forget":
                    with jobs.lock:
                        for k in req.get("keys") or []:
                            t = job["tasks"].get(k)
                            if t and t["state"] != "working":
                                del job["tasks"][k]
                        jobs.save(job)
                    return self.reply(200, {})
                if p == "/api/run":
                    if not has_vice:
                        raise ValueError("x64sc (VICE) is not installed")
                    t = job["tasks"].get((req.get("gid") or "") + "/prg")
                    system = req.get("system")
                    if not t or t["state"] != "done" or system not in ("pal", "ntsc"):
                        raise ValueError("no PRG for that")
                    prg = os.path.join(jobs.dir(job["id"]), t["file"])
                    subprocess.Popen(["x64sc", "-" + system, "-VICIIextpal", "-VICIIpalette",
                                      "pepto-pal.vpl", "-autostartprgmode", "1", prg],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return self.reply(200, {})
                self.fail(404, "not found")
            except ValueError as e:
                self.fail(400, str(e))

    return Handler


def check_opts(o):
    """The page's options, checked: aspect, mc, chroma, palette, size."""
    t = img2c64()
    aspect = o.get("aspect", "both")
    if aspect not in ("both", "pal", "ntsc", "none"):
        raise ValueError("aspect: both, pal, ntsc or none")
    palette = o.get("palette", "tv")
    if palette not in PALETTES:
        raise ValueError("palette: %s" % ", ".join(PALETTES))
    try:
        chroma = t.parse_chroma(str(o.get("chroma", 1)))
        size = list(t.parse_size(o.get("size") or "%dx%d" % (t.MAX_W, t.MAX_H)))
    except Exception as e:
        raise ValueError(str(e))
    return dict(aspect=aspect, mc=bool(o.get("mc")), chroma=chroma, palette=palette,
                size=size)


def main():
    ap = argparse.ArgumentParser(description="vic2orious in the browser (local).")
    ap.add_argument("--port", type=int, default=8064)
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (default 127.0.0.1: this machine only)")
    ap.add_argument("--workers", type=int, default=None,
                    help="processes for quantising and converting (default: one per core)")
    ap.add_argument("--no-browser", action="store_true", help="do not open the page")
    a = ap.parse_args()
    os.makedirs(WEB, exist_ok=True)
    jobs = Jobs(a.workers)
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(jobs))
    url = "http://%s:%d/" % ("127.0.0.1" if a.host in ("0.0.0.0", "") else a.host, a.port)
    print("vic2orious web: %s (jobs in %s; ctrl-c to stop)" % (url, os.path.relpath(WEB)))
    if not a.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        jobs.pool.shutdown(cancel_futures=True)
        jobs.asm.shutdown(cancel_futures=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
