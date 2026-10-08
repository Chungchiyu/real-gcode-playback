const C=require('../src/core.js'); const fs=require('fs'); const t=fs.readFileSync('bambu_flags.gcode','utf8');
function run(flags, align=true){ const j=C.parseGcode(t,{flags}); C.planJob(j,{align}); return j; }
const show=(name,j)=>{ const ext=[...j.flags].filter((f,i)=>(f&C.FL_EXTRUDE)&&!(f&C.FL_SKIP)).length;
  const minY=Math.min(...[...Array(j.moves).keys()].filter(i=>(j.flags[i]&C.FL_EXTRUDE)&&!(j.flags[i]&C.FL_SKIP)).map(i=>j.pts[i*3+4]));
  console.log(name.padEnd(28),'total',j.total.toFixed(1),'| skipped moves',j.skippedMoves,'| drawn extrusions',ext,'| min Y of drawn',minY.toFixed(1)); };
let d=run({}); console.log('flags found:', d.flagsFound.map(f=>`${f.label}=${f.value}${f.count>1?' x'+f.count:''}`).join(', '));
console.log('estimate (slicer)', d.estimate);
show('defaults',d);
show('leveling off',run({g29_before_print_flag:false}));
show('flow cali off',run({extrude_cali_flag:false}));
show('timelapse on',run({timelapse_record_flag:true}));
show('everything on',run({timelapse_record_flag:true,build_plate_detect_flag:true}));
show('cali failed (J0 runs)',run({last_extrude_cali_success:false}));
show('defaults, planner only',run({},false));
// continuity: no drawn travel jumps through skipped region; check every non-skip move starts where previous non-skip ended
const j=run({}); let prev=null, bad=0; for(let k=0;k<j.moves;k++){ if(j.flags[k]&C.FL_SKIP) continue; const s=[j.pts[k*3],j.pts[k*3+1],j.pts[k*3+2]]; if(prev && Math.hypot(s[0]-prev[0],s[1]-prev[1],s[2]-prev[2])>1e-4) bad++; prev=[j.pts[k*3+3],j.pts[k*3+4],j.pts[k*3+5]]; }
console.log('discontinuities across skipped blocks:', bad, '| monotonic t0:', [...j.t0].every((v,i,a)=>i==0||v>=a[i-1]-1e-9));
