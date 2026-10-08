// Regression (fixed in 1.4.3): OrcaSlicer books G29's 260 s on the moves before the G29 line, so its
// progress markers jump ahead of the file. Alignment must not squeeze the following layers to zero.
const fs = require('fs');
const C = require('../src/core.js');
const job = C.parseGcode(fs.readFileSync(__dirname + '/bambu_orca.gcode', 'utf8'), {});
C.planJob(job, { align: true });
const L = job.layers;
const durs = L.slice(1).map((l) => l.t1 - l.t0);
const zero = durs.filter((d) => d < 0.5).length;
// moves should never run much faster than their set speed (planner time is the lower bound)
let tooFast = 0;
for (let k = 0; k < job.moves; k++) {
  if ((job.flags[k] & C.FL_SKIP) || (job.flags[k] & C.FL_DWELL)) continue;
  if (job.plannerDur[k] > 0.05 && job.dur[k] < job.plannerDur[k] * 0.5) tooFast++;
}
console.log('aligned', job.aligned, '| layers with ~0 s:', zero, '| moves >2x faster than planned:', tooFast,
  '| total', job.total.toFixed(0), 's');
if (!job.aligned || zero > 0 || tooFast > 0) { console.error('FAIL timing_test'); process.exit(1); }
