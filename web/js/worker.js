// A web worker running jobs.js for pool.js.
import * as jobs from "./jobs.js";
import { handle } from "./pool.js";

self.onmessage = (e) => handle(jobs, e.data, (m) => self.postMessage(m));
