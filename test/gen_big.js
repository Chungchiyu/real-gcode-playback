const fs=require('fs'); const out=[]; const w=s=>out.push(s);
w('; HEADER_BLOCK_START'); w('; model printing time: 9h 0m 0s; total estimated time: 9h 5m 0s'); w('; HEADER_BLOCK_END');
w('; printable_area = 0x0,180x0,180x180,0x180'); w('; printer_structure = i3'); w('; default_acceleration = 6000');
w('G90'); w('M83'); w('M204 S6000');
let total=0; const layers=320;
for(let L=0;L<layers;L++){ const z=(0.2*(L+1)).toFixed(2);
  w('; CHANGE_LAYER'); w('; Z_HEIGHT: '+z); w('; LAYER_HEIGHT: 0.2'); w('G1 Z'+z+' F1200');
  w(`M73 P${Math.floor(L/layers*100)} R${Math.round((1-L/layers)*545)}`);
  for(let r=0;r<5;r++){ w('; FEATURE: '+(r==0?'Outer wall':'Inner wall')); const R=45-r*0.42; w(`G1 X${(90+R).toFixed(3)} Y90 F30000`);
    for(let k=1;k<=360;k++){const a=k/360*2*Math.PI; w(`G1 X${(90+R*Math.cos(a)).toFixed(3)} Y${(90+R*Math.sin(a)).toFixed(3)} E.02 F${r?12000:9000}`);} }
  w('; FEATURE: Sparse infill'); let flip=false;
  for(let k=0;k<1500;k++){ const t=k/1500; const x=50+80*t; const y=90+ 38*Math.sin(t*60+L*0.3); w(`G1 X${x.toFixed(3)} Y${y.toFixed(3)} E.02 F15000`);}
}
fs.writeFileSync('big.gcode', out.join('\n')); console.log('lines', out.length, 'MB', (out.join('\n').length/1e6).toFixed(1));
