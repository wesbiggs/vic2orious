// jobs.js in a worker thread, for the tests (web/js/worker.js is the browser's).
import { parentPort } from "node:worker_threads";
import * as jobs from "../js/jobs.js";
import { handle } from "../js/pool.js";

parentPort.on("message", (m) => handle(jobs, m, (r) => parentPort.postMessage(r)));
