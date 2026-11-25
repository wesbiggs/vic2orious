// A pool of workers running jobs.js. spawn() makes one worker: an object with
// postMessage(msg), terminate() and the handlers onmessage({data}) and onerror(err) that
// the pool sets (a browser Worker is one).

export class Pool {
  constructor(n, spawn) {
    this.idle = [];
    this.all = [];
    this.queue = [];
    this.jobs = new Map();
    this.next = 0;
    for (let i = 0; i < n; i++) {
      const w = spawn();
      w.onmessage = (e) => this._message(w, e.data);
      w.onerror = (e) => this._fail(e);
      this.idle.push(w);
      this.all.push(w);
    }
  }

  get size() { return this.all.length; }

  run(type, payload, onProgress) {
    return new Promise((resolve, reject) => {
      this.queue.push({ id: this.next++, type, payload, onProgress, resolve, reject });
      this._pump();
    });
  }

  _pump() {
    while (this.idle.length && this.queue.length) {
      const w = this.idle.shift(), j = this.queue.shift();
      this.jobs.set(j.id, j);
      w.postMessage({ id: j.id, type: j.type, payload: j.payload });
    }
  }

  _message(w, m) {
    const j = this.jobs.get(m.id);
    if (!j) return;
    if (m.progress !== undefined) {
      if (j.onProgress) j.onProgress(m.progress);
      return;
    }
    this.jobs.delete(m.id);
    this.idle.push(w);
    this._pump();
    if (m.error !== undefined) j.reject(new Error(m.error));
    else j.resolve(m.result);
  }

  _fail(e) {
    const err = new Error((e && e.message) || "a worker failed to start");
    for (const j of this.jobs.values()) j.reject(err);
    for (const j of this.queue) j.reject(err);
    this.jobs.clear();
    this.queue = [];
  }

  terminate() {
    for (const w of this.all) w.terminate();
    this._fail(new Error("stopped"));
  }
}

/** A job's outcome as a message (shared by the browser and test workers). */
export function handle(jobs, { id, type, payload }, post) {
  try {
    let last = -1;
    const result = jobs[type](payload, (p) => {
      if (p - last >= 0.02 || p === 1) { last = p; post({ id, progress: p }); }
    });
    post({ id, result });
  } catch (e) {
    post({ id, error: describe(e) });
  }
}

function describe(e) {
  if (e && e.constructor && e.constructor.name === "SchedFail") {
    return "the converter found no timing that fits this picture; try another dither or a smaller picture";
  }
  return (e && e.message) || String(e);
}
