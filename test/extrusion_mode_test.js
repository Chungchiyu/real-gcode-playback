const assert = require('node:assert/strict');
const test = require('node:test');
const C = require('../src/core.js');

const klipper = '; gcode_flavor = klipper';

function checkMoves(gcode, deltas) {
  const job = C.parseGcode(gcode);
  assert.deepEqual(Array.from(job.de), deltas.map(Math.fround), 'extrusion deltas');
  assert.deepEqual(Array.from(job.flags, (flags) => Boolean(flags & C.FL_EXTRUDE)),
    deltas.map((delta) => delta > 0), 'extrusion flags');
  return job;
}

test('Klipper M83 survives G90 when the firmware config is at EOF', () => {
  checkMoves(`G1 X0 Y0
M83
G90
G1 X1 E0.5
G1 X2 E0.25
; CONFIG_BLOCK_START
${klipper}
; CONFIG_BLOCK_END`, [0.5, 0.25]);
});

test('Klipper M83 survives a relative Z hop and tool change with decreasing positive E values', () => {
  const job = checkMoves(`${klipper}
G1 X126 Y174
M83
G91
G1 Z1.5 F600
G90
T1
G90
G1 X126.824 Y174.595 E.01833
G1 X127.384 Y174.461 E.0177
G1 X127.874 Y174.428 E.01509`, [0, 0.01833, 0.0177, 0.01509]);
  assert.deepEqual(Array.from(job.pts.slice(-3)), [Math.fround(127.874), Math.fround(174.428), 1.5]);
});

test('Klipper M82 enables absolute E with G90', () => {
  checkMoves(`${klipper}
G1 X0 Y0
M83
G90
M82
G1 X1 E0.5
G1 X2 E0.25
G1 X3 E0.75`, [0.5, -0.25, 0.5]);
});

test('Klipper M82 uses relative E with G91 and resumes absolute E with G90', () => {
  checkMoves(`${klipper}
G1 X0 Y0
G91
M82
G1 X1 E0.5
G1 X1 E0.25
G91
G90
G1 X3 E1`, [0.5, 0.25, 0.25]);
});

test('non-Klipper positioning commands still reset E mode and M82 can override G91', () => {
  const gcode = `G1 X0 Y0
M83
G90
G1 X1 E0.5
G1 X2 E0.25
G91
G1 X1 E0.5
M82
G1 X1 E0.25`;
  checkMoves(gcode, [0.5, -0.25, 0.5, -0.5]);
  checkMoves(`${gcode}\n; gcode_flavor = marlin`, [0.5, -0.25, 0.5, -0.5]);
});
