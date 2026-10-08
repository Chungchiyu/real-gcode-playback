const C = require('../src/core.js'); const fs = require('fs');
for (const f of ['bambu.gcode','marlin.gcode']) {
  const t0=Date.now(); const job = C.parseGcode(fs.readFileSync(f,'utf8')); C.planJob(job);
  const ext=[...job.flags].filter(x=>x&C.FL_EXTRUDE).length;
  console.log(f, 'moves',job.moves,'extrude',ext,'layers',job.layers.length,'events',JSON.stringify(job.events),
   '\n  estimate',job.estimate,'planner',job.plannerTotal.toFixed(1),'total',job.total.toFixed(1),'aligned',job.aligned,'m73',job.m73.length,
   '\n  bed',JSON.stringify([job.bed.x0,job.bed.y0,job.bed.x1,job.bed.y1,job.bed.bedSlinger]),'mode',job.machine.mode,'ms',Date.now()-t0,
   '\n  layer0',JSON.stringify(job.layers[0]),'layer49',JSON.stringify(job.layers[49]));
  // monotonic & sanity
  let bad=0; for(let k=1;k<job.moves;k++){ if(job.t0[k]<job.t0[k-1]-1e-6) bad++; }
  let vbad=0; for(let k=0;k<job.moves;k++){ if(job.vp[k]>job.vnom[k]+1e-3||job.vi[k]>job.vp[k]+1e-3||job.vf[k]>job.vp[k]+1e-3) vbad++; }
  // continuity: exit of k == entry of k+1 for continuous moves
  let jump=0; for(let k=0;k<job.moves-1;k++){ if(job.vnom[k]>0&&job.vnom[k+1]>0&&!(job.flags[k+1]&C.FL_STOP)&&!((job.flags[k]^job.flags[k+1])&C.FL_EONLY)&&Math.abs(job.vf[k]-job.vi[k+1])>1e-3) jump++; }
  // kinematic consistency: vf^2 <= vi^2 + 2aL
  let kin=0; for(let k=0;k<job.moves;k++){ if(job.vnom[k]>0 && job.vf[k]**2 > job.vi[k]**2+2*job.ac[k]*job.len[k]+1e-3) kin++; if(job.vnom[k]>0 && job.vi[k]**2 > job.vf[k]**2+2*job.ac[k]*job.len[k]+1e-3) kin++;}
  const mid = C.moveAt(job, job.total/2); const st=C.stateIn(job, mid, job.total/2);
  console.log('  nonmono',bad,'vbad',vbad,'jump',jump,'kin',kin,'mid move',mid,'feat',C.FEATURES[job.feat[mid]][0],'v',st.v.toFixed(1),'frac',st.frac.toFixed(2));
  const tl = job.layers.map(l=>(l.t1-l.t0).toFixed(1)); console.log('  layer times', tl.slice(0,6).join(','),'...', tl.slice(-4).join(','));
}
