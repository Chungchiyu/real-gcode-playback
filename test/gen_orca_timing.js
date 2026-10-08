// Make bambu_orca.gcode: bambu_flags.gcode with M73 progress and the total estimate rewritten the way
// OrcaSlicer computes them: every block is timed (including ones the printer may skip), G29 counts
// 260 s, and that 260 s is booked on a few moves *before* the G29 line (Orca adds a wait to the
// oldest block still in its planner queue).
const fs = require('fs');
const C = require('../src/core.js');
// a few moves before the start block, as in the real start G-code (wipe, homing moves...)
const text = fs.readFileSync(__dirname + '/bambu_flags.gcode', 'utf8').replace('M1002 judge_flag build_plate_detect_flag',
  'G1 X20 Y20 F6000\nM73 P0 R0\nG1 X60 Y20\nM73 P0 R0\nG1 X60 Y60\nM73 P0 R0\nG1 X20 Y60\nM73 P0 R0\nG1 X20 Y20\nM73 P0 R0\nM1002 judge_flag build_plate_detect_flag');
const job = C.parseGcode(text, { flags: {} });
C.planJob(job, { align: false });
const n = job.moves, t0 = job.plannerT0, dp = job.plannerDur;
let g29 = -1;
for (let k = 0; k < n; k++) if ((job.flags[k] & C.FL_DWELL) && dp[k] > 259) { g29 = k; break; }
if (g29 < 0) throw new Error('no G29 budget found');
const early = Math.max(0, g29 - 3);
const total = job.plannerTotal;
const orcaAt = (k) => { const t = k < n ? t0[k] : total; return (k > early && k <= g29) ? t + 260 : t; };
let i = 0;
const lines = text.split('\n').map((line) => {
  if (!/^M73 P\d+/.test(line)) return line;
  const mk = job.m73[i++];
  const el = orcaAt(mk.move);
  return `M73 P${Math.floor(100 * el / total)} R${Math.round((total - el) / 60)}`;
});
const fmt = (s) => `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
const out = lines.join('\n').replace(/total estimated time: [^\n]+/, 'total estimated time: ' + fmt(total));
fs.writeFileSync(__dirname + '/bambu_orca.gcode', out);
console.log('bambu_orca.gcode', 'G29 at move', g29, 'total', total.toFixed(0), 's, markers', i);
