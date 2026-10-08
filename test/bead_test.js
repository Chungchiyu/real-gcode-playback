// Line cross-section from the G-code: scarf seams and Z contouring keep the width and change the height.
const fs = require('fs');
const C = require('../src/core.js');
const job = C.parseGcode(fs.readFileSync(__dirname + '/bead.gcode', 'utf8'), {});
const rows = { plain: [], scarfStart: [], scarfEnd: [], zaa: [] };
for (let k = 0; k < job.moves; k++) {
  if (!(job.flags[k] & C.FL_EXTRUDE)) continue;
  const li = job.layer[k], z0 = job.pts[k * 3 + 2], z1 = job.pts[k * 3 + 5], y = job.pts[k * 3 + 4];
  const zl = job.layers[li].z;
  const r = { w: job.beadW[k], h: job.beadH[k], z: (z0 + z1) / 2 };
  if (Math.abs(zl - 0.2) < 1e-6) rows.plain.push(r);
  else if (Math.abs(zl - 0.4) < 1e-6 && Math.abs(y - 80) < 1e-6 && Math.abs(job.pts[k * 3 + 1] - 80) < 1e-6 && job.pts[k * 3] < 100.5 && job.pts[k * 3 + 3] <= 100.001) {
    (r.z < 0.4 - 1e-4 ? rows.scarfStart : rows.scarfEnd).push(r);
  } else if (Math.abs(zl - 0.6) < 1e-6) rows.zaa.push(r);
}
let bad = 0;
const check = (name, list, expect) => {
  const ws = list.map((r) => r.w), hs = list.map((r) => r.h);
  const f = (a) => `${Math.min(...a).toFixed(3)}–${Math.max(...a).toFixed(3)}`;
  console.log(name.padEnd(12), 'n', String(list.length).padStart(3), '| width', f(ws), '| height', f(hs));
  const msg = expect(list);
  if (msg) { console.error('  FAIL', msg); bad++; }
};
check('plain', rows.plain, (l) => l.every((r) => Math.abs(r.w - 0.42) < 0.005 && Math.abs(r.h - 0.2) < 1e-4) ? '' : 'expected 0.42 × 0.2');
// a thinner line of the same flow ratio is a little narrower in the rounded-rectangle model:
// w = w0 - h0 (1 - pi/4) (1 - r), at most 0.043 mm here
const wOk = (r) => r.w > 0.37 && r.w < 0.425;
check('scarf start', rows.scarfStart, (l) => l.length === 20 && l.every(wOk) &&
  l[0].h < 0.03 && l[19].h > 0.19 ? '' : 'expected width ~0.42, height ramping 0 -> 0.2');
check('scarf end', rows.scarfEnd, (l) => l.length === 19 && l.every(wOk) &&
  l[0].h > 0.18 && l[l.length - 1].h < 0.02 ? '' : 'expected width ~0.42, height falling 0.2 -> 0 (resting on the start ramp)');
check('Z contour', rows.zaa, (l) => l.every(wOk) && Math.min(...l.map((r) => r.h)) < 0.105 &&
  Math.max(...l.map((r) => r.h)) > 0.19 ? '' : 'expected width ~0.42, height 0.1–0.2');
if (bad) { console.error('FAIL bead_test'); process.exit(1); }
