const C=require('../src/core.js');
function run(g,cfg){const j=C.parseGcode(cfg+'\n'+g); C.planJob(j,{align:false}); return j;}
const cfg='; machine_max_jerk_x = 0.001\n; machine_max_jerk_y = 0.001\n; machine_max_jerk_e = 0.001\n; machine_max_jerk_z = 0.001\n; default_acceleration = 1000\n; travel_acceleration = 1000';
let j=run('G1 X0 Y0 F6000\nG1 X100 F6000',cfg); console.log('straight 100mm @100mm/s a=1000: expect ~1.100 s ->', j.total.toFixed(3));
j=run('G1 X0 Y0\nG1 X10 F6000',cfg); console.log('short 10mm (triangle): expect 2*sqrt(10/1000)=0.200 ->', j.total.toFixed(3));
j=run('G1 X0 Y0\nG1 X50 F6000\nG1 X100 F6000',cfg); console.log('two colinear 50mm: expect 1.100 ->', j.total.toFixed(3));
j=run('G1 X0 Y0\nG1 X50 F6000\nG1 X50 Y50 F6000',cfg); console.log('90deg corner, jerk~0 (full stop): expect 2*0.6=1.200 ->', j.total.toFixed(3));
j=run('G1 X0 Y0\nG4 P500\nG1 X100 F6000',cfg); console.log('dwell 0.5s + 1.1: expect 1.600 ->', j.total.toFixed(3));
j=run('G1 X0 Y0\nG2 X20 Y0 I10 J0 F6000',cfg); console.log('half circle r=10 (len 31.4) G2 ->', j.total.toFixed(3), 'moves', j.moves, 'end', j.pts.slice(-3));
