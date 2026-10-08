/* Playback page: loads G-code, plans it (core.js) and plays it back in real time with Three.js. */
(function () {
  'use strict';
  const C = window.PlaybackCore;
  const $ = (id) => document.getElementById(id);
  const host = (window.orca && typeof window.orca.postMessage === 'function') ? window.orca : null;
  const send = (msg) => { if (host) host.postMessage(msg); };

  /* ------------------------------------------------------------------ preferences */
  const DEFAULT_PREFS = { speed: 10, color: 'feature', travel: false, layerOnly: false, follow: false,
                          motion: 'auto', lines: 'fat', timing: 'aligned', head: true, gantry: true, shade: 'tube', flags: {}, pauseOnLeave: true };
  let prefs = Object.assign({}, DEFAULT_PREFS);
  try { Object.assign(prefs, JSON.parse(localStorage.getItem('orca-playback-prefs') || '{}')); } catch (e) { /* storage may be off */ }
  let prefTimer = 0;
  function savePrefs() {
    clearTimeout(prefTimer);
    prefTimer = setTimeout(() => {
      try { localStorage.setItem('orca-playback-prefs', JSON.stringify(prefs)); } catch (e) { /* ignore */ }
      send({ cmd: 'save_prefs', prefs });
    }, 300);
  }

  /* ------------------------------------------------------------------ small UI helpers */
  function fmtTime(s, withSec) {
    if (!isFinite(s) || s < 0) s = 0;
    s = Math.floor(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    if (h) return h + ':' + String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
    return m + ':' + String(sec).padStart(2, '0');
  }
  function fmtLong(s) {
    s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return (h ? h + 'h ' : '') + (h || m ? m + 'm ' : '') + sec + 's';
  }
  let toastTimer = 0;
  function toast(text, isErr) {
    const t = $('toast'); t.textContent = text; t.className = 'overlay show' + (isErr ? ' err' : '');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.className = 'overlay'; }, isErr ? 6000 : 2800);
  }
  function busy(text, frac) {
    const b = $('busy');
    if (text == null) { b.style.display = 'none'; return; }
    b.style.display = 'grid'; $('busyText').textContent = text;
    $('busyBar').style.width = Math.round((frac || 0) * 100) + '%';
  }
  const nextFrame = () => new Promise((r) => setTimeout(r, 0));

  /* ------------------------------------------------------------------ colours */
  const RANGE = ['#0b2c7a', '#135985', '#1c8891', '#04d60f', '#aaf200', '#fcf903', '#f5ce0a', '#d16830', '#c2523c', '#942616'];
  const hexRGB = (h) => { h = String(h || '#888').replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join('');
                          const v = parseInt(h.substring(0, 6), 16); return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255]; };
  const RANGE_RGB = RANGE.map(hexRGB);
  const FEAT_RGB = C.FEATURES.map(f => hexRGB(f[1]));
  function rampRGB(t, out) {
    t = Math.max(0, Math.min(1, t)) * (RANGE_RGB.length - 1);
    const i = Math.min(RANGE_RGB.length - 2, Math.floor(t)), f = t - i, a = RANGE_RGB[i], b = RANGE_RGB[i + 1];
    out[0] = a[0] + (b[0] - a[0]) * f; out[1] = a[1] + (b[1] - a[1]) * f; out[2] = a[2] + (b[2] - a[2]) * f;
  }
  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  /* ------------------------------------------------------------------ three.js scene */
  const canvas = $('gl');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: false });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.5, 5000);
  camera.up.set(0, 0, 1);
  const controls = new THREE.OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.dampingFactor = 0.12; controls.screenSpacePanning = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 0.6); sun.position.set(-1, -2, 3); scene.add(sun);

  const bedGroup = new THREE.Group(); scene.add(bedGroup);    // bed + everything printed on it
  const headGroup = new THREE.Group(); scene.add(headGroup);  // nozzle
  const gantry = new THREE.Group(); scene.add(gantry);
  let bedMesh = null;

  function buildHead() {
    const metal = new THREE.MeshLambertMaterial({ color: 0xc8ccd2 });
    // translucent hot-end body so it never hides the line being printed
    const block = new THREE.MeshLambertMaterial({ color: 0x59616b, transparent: true, opacity: 0.38, depthWrite: false });
    const cone = new THREE.Mesh(new THREE.ConeGeometry(1.4, 3.5, 24), metal);
    cone.rotation.x = -Math.PI / 2; cone.position.z = 1.75;        // tip at z = 0
    const body = new THREE.Mesh(new THREE.BoxGeometry(9, 9, 7), block);
    body.position.z = 3.5 + 3.5;
    const tip = new THREE.Mesh(new THREE.SphereGeometry(0.45, 16, 12), new THREE.MeshBasicMaterial({ color: 0xff5a1f }));
    headGroup.add(cone, body, tip);
    headGroup.userData.body = body;
  }
  buildHead();
  const beamMat = new THREE.MeshLambertMaterial({ color: 0x5b626b, transparent: true, opacity: 0.28, depthWrite: false });
  const beam = new THREE.Mesh(new THREE.BoxGeometry(1, 4, 4), beamMat);
  gantry.add(beam);

  function bedTexture(w, h) {
    const px = 4, cw = Math.min(2048, Math.ceil(w * px)), ch = Math.min(2048, Math.ceil(h * px));
    const c = document.createElement('canvas'); c.width = cw; c.height = ch;
    const g = c.getContext('2d');
    g.fillStyle = '#2b2f35'; g.fillRect(0, 0, cw, ch);
    const sx = cw / w, sy = ch / h;
    for (let mm = 0; mm <= Math.max(w, h); mm += 10) {
      const major = mm % 50 === 0;
      g.strokeStyle = major ? 'rgba(255,255,255,.22)' : 'rgba(255,255,255,.09)';
      g.lineWidth = major ? 2 : 1;
      if (mm <= w) { g.beginPath(); g.moveTo(mm * sx, 0); g.lineTo(mm * sx, ch); g.stroke(); }
      if (mm <= h) { g.beginPath(); g.moveTo(0, ch - mm * sy); g.lineTo(cw, ch - mm * sy); g.stroke(); }
    }
    const tex = new THREE.CanvasTexture(c);
    tex.anisotropy = 4;
    return tex;
  }
  function buildBed(bed) {
    if (bedMesh) { bedGroup.remove(bedMesh); bedMesh.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); }); }
    const w = bed.x1 - bed.x0, h = bed.y1 - bed.y0;
    const shape = new THREE.Shape(bed.poly.map(p => new THREE.Vector2(p[0], p[1])));
    const geo = new THREE.ShapeGeometry(shape);
    // UVs across the bounding box so the grid texture lines up with bed millimetres
    const pos = geo.attributes.position, uv = new Float32Array(pos.count * 2);
    for (let i = 0; i < pos.count; i++) { uv[i * 2] = (pos.getX(i) - bed.x0) / w; uv[i * 2 + 1] = (pos.getY(i) - bed.y0) / h; }
    geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    const mat = new THREE.MeshBasicMaterial({ map: bedTexture(w, h) });
    const plate = new THREE.Mesh(geo, mat);
    plate.position.z = -0.05;
    const slab = new THREE.Mesh(new THREE.BoxGeometry(w + 6, h + 6, 4), new THREE.MeshLambertMaterial({ color: 0x1a1d21 }));
    slab.position.set(bed.x0 + w / 2, bed.y0 + h / 2, -2.1);
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.ShapeGeometry(shape)),
                                        new THREE.LineBasicMaterial({ color: 0x8a939c }));
    edge.position.z = 0.01;
    bedMesh = new THREE.Group(); bedMesh.add(slab, plate, edge);
    bedGroup.add(bedMesh);
    beam.scale.set(w + 40, 1, 1);
  }

  /* ------------------------------------------------------------------ path buffers */
  const R = {                    // render state built per job
    segMove: null,              // Uint32Array: extrusion segment -> move index
    extPrefix: null,            // Uint32Array(moves+1): extrusion segments completed before move k
    travelPrefix: null,         // Uint32Array(moves+1): travel segments before move k
    pos: null, col: null,       // Float32Array 6 per segment
    main: null,                 // object rendering every segment, progressively revealed
    layerObj: null, layerObjLayer: -1,
    partial: null,              // the segment being printed right now
    travel: null,
  };
  let lineMat = null, lineMatPartial = null, thinMat = null;
  function lineWidth() { return Math.max(0.2, (job && job.machine.nozzle) ? job.machine.nozzle * 1.05 : 0.42); }

  function makeLines(pos, col, count) {
    if (prefs.lines === 'thin') {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      g.setAttribute('color', new THREE.BufferAttribute(col, 3));
      g.setDrawRange(0, count * 2);
      const o = new THREE.LineSegments(g, thinMat); o.frustumCulled = false;
      o.userData.thin = true; return o;
    }
    const g = new THREE.LineSegmentsGeometry();
    g.setPositions(pos); g.setColors(col);
    g.instanceCount = count;
    const o = new THREE.LineSegments2(g, lineMat); o.frustumCulled = false;
    return o;
  }
  function setCount(o, count) {
    if (!o) return;
    if (o.userData.thin) o.geometry.setDrawRange(0, count * 2);
    else o.geometry.instanceCount = count;
  }
  function disposeObj(o) { if (!o) return; bedGroup.remove(o); o.geometry.dispose(); }

  /* LineMaterial already finds, per pixel, how far the view ray passes from the line's axis
     (WORLD_UNITS mode). That is exactly a cylinder: turn the distance into a surface normal and
     light it, so extrusions read as round beads instead of flat ribbons. */
  const shadeUniform = { value: 1 };
  function shadedLineMaterial() {
    const m = new THREE.LineMaterial({ vertexColors: true, worldUnits: true, linewidth: 0.42 });
    m.onBeforeCompile = (shader) => {
      shader.uniforms.shadeMode = shadeUniform;
      shader.fragmentShader = shader.fragmentShader
        .replace('uniform float opacity;', 'uniform float opacity;\nuniform float shadeMode;')
        .replace('#include <color_fragment>', `#include <color_fragment>
        #ifdef WORLD_UNITS
          if ( shadeMode > 0.5 ) {
            float r = linewidth * 0.5;
            float s = clamp( len / r, 0.0, 1.0 );
            vec3 ld = normalize( lineDir );
            vec3 toCam = -normalize( p2 );
            vec3 c = toCam - dot( toCam, ld ) * ld;
            c = length( c ) > 1e-5 ? normalize( c ) : toCam;
            vec3 side = len > 1e-6 ? -delta / len : vec3( 0.0 );
            vec3 N = normalize( side * s + c * sqrt( max( 0.0, 1.0 - s * s ) ) );
            vec3 L = normalize( vec3( -0.35, 0.6, 0.72 ) );
            float diff = max( dot( N, L ), 0.0 );
            float spec = pow( max( dot( N, normalize( L + toCam ) ), 0.0 ), 36.0 ) * 0.22;
            diffuseColor.rgb = diffuseColor.rgb * ( 0.34 + 0.76 * diff ) + spec;
          }
        #endif`);
    };
    return m;
  }

  function ensureMaterials() {
    if (!lineMat) {
      lineMat = shadedLineMaterial(); lineMatPartial = shadedLineMaterial();
      thinMat = new THREE.LineBasicMaterial({ vertexColors: true });
    }
    lineMat.linewidth = lineWidth(); lineMatPartial.linewidth = lineWidth();
    resize();
  }

  function buildPaths() {
    const n = job.moves, F = job.flags, P = job.pts;
    let segs = 0, travels = 0;
    for (let k = 0; k < n; k++) { if (F[k] & C.FL_SKIP) continue; if (F[k] & C.FL_EXTRUDE) segs++; else if (F[k] & C.FL_TRAVEL) travels++; }
    const segMove = new Uint32Array(segs), extPrefix = new Uint32Array(n + 1), travelPrefix = new Uint32Array(n + 1);
    const pos = new Float32Array(segs * 6), tpos = new Float32Array(Math.max(1, travels) * 6);
    let s = 0, tr = 0;
    for (let k = 0; k < n; k++) {
      extPrefix[k] = s; travelPrefix[k] = tr;
      if (F[k] & C.FL_SKIP) continue;               // blocks the printer won't run are not drawn
      if (F[k] & C.FL_EXTRUDE) {
        segMove[s] = k;
        pos.set(P.subarray(k * 3, k * 3 + 6), s * 6);
        s++;
      } else if (F[k] & C.FL_TRAVEL) {
        tpos.set(P.subarray(k * 3, k * 3 + 6), tr * 6);
        tr++;
      }
    }
    extPrefix[n] = s; travelPrefix[n] = tr;
    R.segMove = segMove; R.extPrefix = extPrefix; R.travelPrefix = travelPrefix; R.pos = pos;
    R.col = new Float32Array(segs * 6);
    computeColors();
    rebuildObjects();
    // travel lines
    if (R.travel) disposeObj(R.travel);
    const tg = new THREE.BufferGeometry(); tg.setAttribute('position', new THREE.BufferAttribute(tpos, 3)); tg.setDrawRange(0, 0);
    R.travel = new THREE.LineSegments(tg, new THREE.LineBasicMaterial({ color: 0x4fa3ff, transparent: true, opacity: 0.55 }));
    R.travel.frustumCulled = false;
    bedGroup.add(R.travel);
  }

  function rebuildObjects() {
    ensureMaterials();
    disposeObj(R.main); disposeObj(R.layerObj); disposeObj(R.partial);
    R.main = makeLines(R.pos, R.col, 0); bedGroup.add(R.main);
    R.layerObj = null; R.layerObjLayer = -1;
    const pg = new THREE.LineSegmentsGeometry();
    pg.setPositions(new Float32Array(6)); pg.setColors(new Float32Array(6));
    R.partial = prefs.lines === 'thin'
      ? (() => { const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
                 g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(6), 3)); const o = new THREE.LineSegments(g, thinMat); o.userData.thin = true; o.frustumCulled = false; return o; })()
      : (() => { const o = new THREE.LineSegments2(pg, lineMatPartial); o.frustumCulled = false; return o; })();
    bedGroup.add(R.partial);
    lastShown = -1;
  }

  /* colour by the selected mode; also fills the legend */
  let colorRange = null;
  function percentile(vals, p) {
    if (!vals.length) return 0;
    const a = Float32Array.from(vals).sort(); return a[Math.min(a.length - 1, Math.max(0, Math.floor(p * (a.length - 1))))];
  }
  function computeColors() {
    const mode = prefs.color, segs = R.segMove.length, col = R.col, rgb = [0, 0, 0];
    const filArea = Math.PI * Math.pow(job.machine.filamentDiameter / 2, 2);
    const filColors = String(job.config.filament_colour || job.config.extruder_colour || '').split(/[;,]/).map(s => s.trim()).filter(Boolean);
    const filRGB = filColors.map(hexRGB);
    let value = null, unit = '';
    if (mode === 'speed') { value = (k) => job.vp[k]; unit = 'mm/s'; }
    else if (mode === 'fcmd') { value = (k) => job.fcmd[k]; unit = 'mm/s'; }
    else if (mode === 'flow') { value = (k) => job.plannerDur[k] > 0 ? job.de[k] * filArea / job.plannerDur[k] : 0; unit = 'mm³/s'; }
    else if (mode === 'layertime') { value = (k) => { const L = job.layers[job.layer[k]]; return L ? L.t1 - L.t0 : 0; }; unit = 's'; }
    colorRange = null;
    if (value) {
      const sample = []; const stride = Math.max(1, Math.floor(segs / 20000));
      for (let s = 0; s < segs; s += stride) sample.push(value(R.segMove[s]));
      let lo = percentile(sample, 0.01), hi = percentile(sample, 0.99);
      if (hi - lo < 1e-6) { hi = lo + 1; }
      colorRange = { lo, hi, unit };
      for (let s = 0; s < segs; s++) {
        rampRGB((value(R.segMove[s]) - lo) / (hi - lo), rgb);
        col[s * 6] = col[s * 6 + 3] = rgb[0]; col[s * 6 + 1] = col[s * 6 + 4] = rgb[1]; col[s * 6 + 2] = col[s * 6 + 5] = rgb[2];
      }
    } else {
      for (let s = 0; s < segs; s++) {
        const k = R.segMove[s];
        const c = mode === 'filament' ? (filRGB[job.tool[k]] || FEAT_RGB[0]) : FEAT_RGB[featVisible[job.feat[k]] === false ? 0 : job.feat[k]];
        col[s * 6] = col[s * 6 + 3] = c[0]; col[s * 6 + 1] = col[s * 6 + 4] = c[1]; col[s * 6 + 2] = col[s * 6 + 5] = c[2];
      }
    }
    applyShade();
    renderLegend(filColors);
  }
  function applyShade() {
    shadeUniform.value = (prefs.shade === 'tube' || prefs.shade === 'layers') ? 1 : 0;
    const col = R.col, segs = R.segMove.length;
    if (prefs.shade === 'layers') {
      // alternate layers slightly brighter / darker so individual layers are easy to count
      for (let s = 0; s < segs; s++) {
        const f = (job.layer[R.segMove[s]] & 1) ? 0.84 : 1.06;
        for (let q = 0; q < 6; q++) col[s * 6 + q] = Math.min(1, col[s * 6 + q] * f);
      }
    } else if (prefs.shade === 'height') {
      const z0 = job.bed.model.minZ, z1 = Math.max(z0 + 1e-3, job.bed.model.maxZ), P = job.pts;
      for (let s = 0; s < segs; s++) {
        const z = P[R.segMove[s] * 3 + 5];
        const f = 0.45 + 0.6 * Math.max(0, Math.min(1, (z - z0) / (z1 - z0)));
        for (let q = 0; q < 6; q++) col[s * 6 + q] = Math.min(1, col[s * 6 + q] * f);
      }
    }
    dirty = true;
  }
  const featVisible = {};

  function renderLegend(filColors) {
    const el = $('legend'); const mode = prefs.color;
    let html = '';
    if (mode === 'feature') {
      const used = new Set(); for (let s = 0; s < R.segMove.length; s += 7) used.add(job.feat[R.segMove[s]]);
      html = '<h4>Line type</h4>' + C.FEATURES.map((f, i) => used.has(i)
        ? '<div class="row"><span class="sw" style="background:' + f[1] + '"></span>' + f[0] + '</div>' : '').join('');
    } else if (mode === 'filament') {
      const used = new Set(); for (let s = 0; s < R.segMove.length; s += 7) used.add(job.tool[R.segMove[s]]);
      html = '<h4>Filament</h4>' + [...used].sort((a, b) => a - b).map(t =>
        '<div class="row"><span class="sw" style="background:' + (filColors[t] || '#9aa3ab') + '"></span>Filament ' + (t + 1) + '</div>').join('');
    } else if (colorRange) {
      const title = { speed: 'Actual speed (peak)', fcmd: 'Set speed', flow: 'Volumetric flow', layertime: 'Layer time' }[mode];
      const f = (v) => (v >= 100 ? Math.round(v) : v.toFixed(1)) + ' ' + colorRange.unit;
      html = '<h4>' + title + '</h4><div class="grad" style="background:linear-gradient(90deg,' + RANGE.join(',') + ')"></div>' +
             '<div class="ends"><span>' + f(colorRange.lo) + '</span><span>' + f(colorRange.hi) + '</span></div>';
    }
    el.innerHTML = html; el.hidden = !html || !job;
  }

  /* ------------------------------------------------------------------ playback state */
  let job = null, gcodeText = null, lineStarts = null, currentMeta = {};
  let simT = 0, playing = false, lastFrame = 0, lastShown = -1, dirty = true;
  let curMove = 0;
  let hudTimer = 0;
  const bedCenter = new THREE.Vector3();

  function bedSlinger() {
    if (prefs.motion === 'bed') return true;
    if (prefs.motion === 'head') return false;
    return !!(job && job.bed.bedSlinger);
  }

  function nozzleAt(t) {
    const k = C.moveAt(job, t);
    const st = C.stateIn(job, k, t);
    const P = job.pts, a = k * 3;
    return { k, frac: st.frac, v: st.v,
             x: P[a] + (P[a + 3] - P[a]) * st.frac, y: P[a + 1] + (P[a + 4] - P[a + 1]) * st.frac, z: P[a + 2] + (P[a + 5] - P[a + 2]) * st.frac };
  }

  function setLayerOnlyObject(layerIdx) {
    if (R.layerObjLayer === layerIdx && R.layerObj) return;
    disposeObj(R.layerObj); R.layerObj = null; R.layerObjLayer = layerIdx;
    const L = job.layers[layerIdx]; if (!L) return;
    const a = R.extPrefix[L.first], b = R.extPrefix[layerIdx + 1 < job.layers.length ? job.layers[layerIdx + 1].first : job.moves];
    const pos = R.pos.slice(a * 6, b * 6), col = R.col.slice(a * 6, b * 6);
    R.layerObj = makeLines(pos, col, 0); R.layerObj.userData.base = a;
    bedGroup.add(R.layerObj);
  }

  const tmpCol = [0, 0, 0];
  function updateScene(force) {
    if (!job) return;
    const nz = nozzleAt(simT);
    curMove = nz.k;
    const F = job.flags;
    const done = R.extPrefix[nz.k];           // segments fully printed before this move
    const layerIdx = job.layer[nz.k];

    if (prefs.layerOnly) {
      R.main.visible = false;
      setLayerOnlyObject(layerIdx);
      if (R.layerObj) { R.layerObj.visible = true; setCount(R.layerObj, Math.max(0, done - R.layerObj.userData.base)); }
    } else {
      R.main.visible = true; if (R.layerObj) R.layerObj.visible = false;
      if (done !== lastShown || force) { setCount(R.main, done); lastShown = done; }
    }

    // the segment being extruded right now, drawn up to the nozzle
    if ((F[nz.k] & C.FL_EXTRUDE) && nz.frac > 0) {
      const P = job.pts, a = nz.k * 3, s = done;
      const p = new Float32Array([P[a], P[a + 1], P[a + 2], nz.x, nz.y, nz.z]);
      const c = R.col.slice(s * 6, s * 6 + 6);
      if (R.partial.userData.thin) {
        R.partial.geometry.attributes.position.array.set(p); R.partial.geometry.attributes.position.needsUpdate = true;
        R.partial.geometry.attributes.color.array.set(c); R.partial.geometry.attributes.color.needsUpdate = true;
      } else { R.partial.geometry.setPositions(p); R.partial.geometry.setColors(c); }
      R.partial.visible = true;
    } else R.partial.visible = false;

    // travel moves of the current layer up to now
    R.travel.visible = prefs.travel;
    if (prefs.travel) {
      const L = job.layers[layerIdx];
      const a = R.travelPrefix[L ? L.first : 0], b = R.travelPrefix[nz.k + ((F[nz.k] & C.FL_TRAVEL) && nz.frac >= 1 ? 1 : 0)];
      R.travel.geometry.setDrawRange(a * 2, Math.max(0, b - a) * 2);
    }

    // nozzle, bed and gantry
    const slinger = bedSlinger();
    const cy = (job.bed.y0 + job.bed.y1) / 2;
    if (slinger) {
      bedGroup.position.set(0, cy - nz.y, 0);
      headGroup.position.set(nz.x, cy, nz.z);
      gantry.position.set((job.bed.x0 + job.bed.x1) / 2, cy, nz.z + 12);
    } else {
      bedGroup.position.set(0, 0, 0);
      headGroup.position.set(nz.x, nz.y, nz.z);
      gantry.position.set((job.bed.x0 + job.bed.x1) / 2, nz.y, nz.z + 12);
    }
    if (prefs.follow) {
      const target = headGroup.position.clone();
      const delta = target.sub(controls.target).multiplyScalar(0.18);
      controls.target.add(delta); camera.position.add(delta);
    }
    hudState = nz;
    dirty = true;
  }

  let hudState = null;
  function updateHud() {
    if (!job || !hudState) return;
    const nz = hudState, k = nz.k, L = job.layer[k], layer = job.layers[L];
    const startOffset = job.layers[0] && job.layers[0].start ? 1 : 0;
    const layerCount = job.layers.length - startOffset;
    $('hTime').textContent = fmtTime(simT);
    $('hTotal').textContent = fmtTime(job.total);
    $('hRemain').textContent = fmtLong(Math.max(0, job.total - simT));
    if (layer && layer.start) $('hLayer').textContent = 'start G-code';
    else $('hLayer').textContent = (L + 1 - startOffset) + ' / ' + layerCount;
    const lp = layer ? (simT - layer.t0) / Math.max(1e-6, layer.t1 - layer.t0) : 0;
    $('hLayerBar').style.width = Math.round(Math.max(0, Math.min(1, lp)) * 100) + '%';
    $('hZ').textContent = nz.z.toFixed(2) + ' mm' + (layer && layer.h ? '  ·  h ' + layer.h.toFixed(2) : '');
    const F = job.flags[k];
    let kind;
    if (F & C.FL_DWELL) kind = '<span class="muted">Waiting</span>';
    else if (F & C.FL_EONLY) kind = '<span class="muted">' + (job.de[k] < 0 ? 'Retract' : (job.feat[k] === 18 ? 'Flush / purge' : 'Unretract / prime')) + '</span>';
    else if (F & C.FL_TRAVEL) kind = '<span class="muted">Travel</span>';
    else { const f = C.FEATURES[job.feat[k]]; kind = '<span class="dot" style="background:' + f[1] + '"></span>' + f[0]; }
    $('hFeat').innerHTML = kind;
    const slow = job.aligned && job.plannerDur[k] > 0 ? 1 : 1;
    $('hSpeed').textContent = Math.round(nz.v * slow) + ' mm/s';
    $('hSpeedSet').textContent = (F & C.FL_DWELL) ? '' : 'of ' + Math.round(job.fcmd[k]) + ' set';
    const filArea = Math.PI * Math.pow(job.machine.filamentDiameter / 2, 2);
    const flow = (F & C.FL_EXTRUDE) && job.len[k] > 0 ? nz.v * job.de[k] / job.len[k] * filArea : 0;
    $('hFlow').textContent = (F & C.FL_EXTRUDE) ? flow.toFixed(1) + ' mm³/s' : '–';
    $('hAcc').textContent = (F & C.FL_DWELL) ? '–' : Math.round(job.ac[k]) + ' mm/s²';
    const fc = String(job.config.filament_colour || '').split(/[;,]/)[job.tool[k]];
    $('hTool').innerHTML = (fc ? '<span class="dot" style="background:' + fc.trim() + '"></span>' : '') + (job.tool[k] + 1);
    $('hSrc').textContent = sourceLine(job.line[k]);
    if (codeOpen) {
      const cur = job.line[k];
      if (cur !== codeLastCur) { codeLastCur = cur; codeFollowTo(!playing); renderCode(); }
    }
    // bottom bar
    $('cTime').textContent = fmtTime(simT); $('cTotal').textContent = fmtTime(job.total);
    $('cPct').textContent = Math.floor(simT / Math.max(1e-9, job.total) * 100) + '%';
    if (document.activeElement !== $('layerIn')) $('layerIn').value = Math.max(1, L + 1 - startOffset);
    drawTimeline();
  }

  function ensureLineStarts() {
    if (!lineStarts && gcodeText) {
      // index line starts once, lazily
      const starts = [0]; let i = -1;
      while ((i = gcodeText.indexOf('\n', i + 1)) >= 0) starts.push(i + 1);
      if (starts[starts.length - 1] >= gcodeText.length) starts.pop();     // no empty last line
      lineStarts = Uint32Array.from(starts);
    }
    return lineStarts;
  }
  function lineText(no, max) {
    if (!gcodeText || !no || !ensureLineStarts() || no > lineStarts.length) return '';
    const a = lineStarts[no - 1], b = no < lineStarts.length ? lineStarts[no] - 1 : gcodeText.length;
    return gcodeText.substring(a, Math.min(b, a + (max || 200))).replace(/\r$/, '');
  }
  function sourceLine(no) { return no ? no + ':  ' + lineText(no, 160).trim() : ''; }

  /* ------------------------------------------------------------------ G-code panel
     A virtual list: only the rows in view exist, so a million-line file scrolls as easily as a
     short one. While following, it glides to keep the running line centred; scrolling by hand
     pauses following until "Follow" is pressed again. Clicking a line seeks to it. */
  const ROW = 18, MAX_SCROLL_H = 1.2e7;
  const codeScroll = $('codeScroll'), codeRows = $('codeRows'), codeSpacer = $('codeSpacer');
  let codeOpen = false, codeFollow = true, codeTarget = null, codeLastCur = -1, flashLine = 0, flashUntil = 0;
  function codeCount() { return ensureLineStarts() ? lineStarts.length : 0; }
  function codeGeom() {
    const n = codeCount(), view = codeScroll.clientHeight || 288;
    const realH = n * ROW, H = Math.min(realH, MAX_SCROLL_H), vis = Math.floor(view / ROW);
    return { n, view, H, scaled: realH > MAX_SCROLL_H, vis };
  }
  function firstLineAt(top, g) {      // 0-based index of the first row shown for a scrollTop
    if (!g.scaled) return Math.floor(top / ROW);
    return Math.round(top / Math.max(1, g.H - g.view) * Math.max(0, g.n - g.vis));
  }
  function scrollTopFor(first, g) {
    first = Math.max(0, Math.min(Math.max(0, g.n - g.vis), first));
    if (!g.scaled) return first * ROW;
    return first / Math.max(1, g.n - g.vis) * Math.max(1, g.H - g.view);
  }
  const escHtml = (t) => t.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  function highlight(t) {
    let code = t, comment = '';
    const c = t.indexOf(';'); if (c >= 0) { code = t.substring(0, c); comment = t.substring(c); }
    let html = escHtml(code).replace(/^(\s*)([GMT]\d+(?:\.\d+)?)/i, (m, sp, cmd) =>
      sp + '<span class="' + (/^[mt]/i.test(cmd) ? 'km' : 'k') + '">' + cmd + '</span>');
    html = html.replace(/(\s)([XYZEFIJRSP])(?=[-\d.])/g, '$1<span class="a">$2</span>');
    if (comment) html += '<span class="c">' + escHtml(comment) + '</span>';
    return html;
  }
  function renderCode() {
    if (!codeOpen || !job) return;
    const g = codeGeom();
    codeSpacer.style.height = g.H + 'px';
    const top = codeScroll.scrollTop, first = firstLineAt(top, g);
    const offset = g.scaled ? top : first * ROW;
    const cur = job.line[curMove] || 0;
    let html = '';
    for (let i = first; i < Math.min(g.n, first + g.vis + 3); i++) {
      const no = i + 1;
      html += '<div class="ln' + (no === cur ? ' cur' : no < cur ? ' past' : '') + (no === flashLine && performance.now() < flashUntil ? ' flash' : '') + '" data-line="' + no + '"><span class="no">' + no +
              '</span><span class="tx">' + highlight(lineText(no, 220)) + '</span></div>';
    }
    codeRows.style.transform = 'translateY(' + offset + 'px)';
    codeRows.innerHTML = html;
    $('codeInfo').textContent = 'Line ' + (cur || '–') + ' of ' + g.n.toLocaleString();
  }
  /* Following keeps the running line pinned to the middle row. While playing it moves straight
     there (an eased glide falls behind at high speeds and the highlight drifts out of view);
     the glide is only used for one-off jumps, such as pressing Follow. */
  function codeFollowTo(animate) {
    if (!codeOpen || !codeFollow || !job) return;
    const g = codeGeom(), cur = (job.line[curMove] || 1) - 1;
    const target = scrollTopFor(cur - Math.floor((g.vis - 1) / 2), g);
    if (!animate || playing || Math.abs(target - codeScroll.scrollTop) > g.view * 40) { setCodeScroll(target); codeTarget = null; }
    else codeTarget = target;
  }
  function setCodeScroll(v) { codeScroll.scrollTop = v; renderCode(); }
  function stepCodeScroll() {      // called every animation frame: ease towards the target
    if (codeTarget == null || !codeOpen) return;
    const cur = codeScroll.scrollTop, d = codeTarget - cur;
    if (Math.abs(d) < 0.6) { setCodeScroll(codeTarget); codeTarget = null; return; }
    setCodeScroll(cur + d * 0.22);
  }
  function setFollow(on) {
    codeFollow = on; $('codeFollow').classList.toggle('on', on);
    $('codeFollow').textContent = on ? 'Following' : 'Follow';
    if (on) codeFollowTo(true);
  }
  function setCodeOpen(open) {
    codeOpen = open && !!job;
    $('codePanel').classList.toggle('open', codeOpen);
    $('codePanel').setAttribute('aria-hidden', String(!codeOpen));
    $('codeToggle').setAttribute('aria-expanded', String(codeOpen));
    if (codeOpen) { renderCode(); setFollow(true); codeFollowTo(false); }
  }
  $('codeToggle').onclick = () => setCodeOpen(!codeOpen);
  $('codeFollow').onclick = () => setFollow(true);
  codeScroll.addEventListener('scroll', renderCode);
  // only real user input stops following (programmatic scrolls must not)
  const userScrolled = () => { if (codeFollow) setFollow(false); codeTarget = null; };
  codeScroll.addEventListener('wheel', userScrolled, { passive: true });
  codeScroll.addEventListener('touchstart', userScrolled, { passive: true });
  codeScroll.addEventListener('pointerdown', (e) => { if (e.target === codeScroll) userScrolled(); });   // scrollbar drag
  codeScroll.addEventListener('keydown', (e) => {
    if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(e.key)) { e.stopPropagation(); userScrolled(); }
  });
  codeRows.addEventListener('click', (e) => {
    const row = e.target.closest('.ln'); if (!row || !job) return;
    const no = parseInt(row.dataset.line, 10);
    // the first move at or after this line; comments and settings jump to the move that follows
    const L = job.line; let lo = 0, hi = job.moves - 1;
    if (!(hi >= 0)) return;
    if (no > L[hi]) { seek(job.total); }
    else {
      while (lo < hi) { const mid = (lo + hi) >> 1; if (L[mid] < no) lo = mid + 1; else hi = mid; }
      seek(job.t0[lo] + (job.dur[lo] > 0 ? Math.min(1e-4, job.dur[lo] / 2) : 0));
    }
    flashLine = no; flashUntil = performance.now() + 600;
    renderCode();
  });

  /* ------------------------------------------------------------------ timeline */
  const tlc = $('tlc'), tg = tlc.getContext('2d');
  let tlHover = -1;
  function drawTimeline() {
    const dpr = window.devicePixelRatio || 1, w = tlc.clientWidth, h = tlc.clientHeight;
    if (tlc.width !== Math.round(w * dpr) || tlc.height !== Math.round(h * dpr)) { tlc.width = Math.round(w * dpr); tlc.height = Math.round(h * dpr); }
    tg.setTransform(dpr, 0, 0, dpr, 0, 0);
    tg.clearRect(0, 0, w, h);
    const fg = cssVar('--fg', '#ddd'), accent = cssVar('--accent', '#009688');
    const trackY = 14, trackH = 12;
    tg.fillStyle = 'rgba(127,137,142,.18)';
    roundRect(tg, 0, trackY, w, trackH, 6); tg.fill();
    if (!job) return;
    const X = (t) => (t / Math.max(1e-9, job.total)) * w;
    // layer bands: alternating shades, so long layers read as long
    for (let i = 0; i < job.layers.length; i++) {
      const L = job.layers[i]; const x0 = X(L.t0), x1 = X(L.t1);
      if (i % 2) { tg.fillStyle = 'rgba(127,137,142,.12)'; tg.fillRect(x0, trackY, Math.max(0.5, x1 - x0), trackH); }
    }
    tg.save(); roundRect(tg, 0, trackY, w, trackH, 6); tg.clip();
    tg.fillStyle = accent; tg.globalAlpha = 0.85; tg.fillRect(0, trackY, X(simT), trackH); tg.globalAlpha = 1; tg.restore();
    // layer ticks
    const n = job.layers.length, every = n > 400 ? 50 : n > 150 ? 20 : n > 50 ? 10 : 5;
    tg.fillStyle = fg; tg.globalAlpha = 0.35;
    const startOffset = job.layers[0] && job.layers[0].start ? 1 : 0;
    for (let i = startOffset; i < n; i++) {
      const num = i + 1 - startOffset;
      if (num % every) continue;
      const x = X(job.layers[i].t0); tg.fillRect(x, trackY + trackH, 1, 4);
    }
    tg.globalAlpha = 1;
    // events
    const filColors = String(job.config.filament_colour || '').split(/[;,]/);
    for (const ev of job.events) {
      const t = ev.move < job.moves ? job.t0[ev.move] : job.total, x = X(t);
      tg.fillStyle = ev.kind === 'pause' ? '#d9534f' : ev.kind === 'heat' ? '#e0913a' : (filColors[ev.tool] || '#7fb2ff').trim();
      tg.beginPath(); tg.moveTo(x, trackY - 1); tg.lineTo(x - 5, trackY - 9); tg.lineTo(x + 5, trackY - 9); tg.closePath(); tg.fill();
      tg.strokeStyle = 'rgba(0,0,0,.4)'; tg.lineWidth = 1; tg.stroke();
    }
    // playhead
    const px = X(simT);
    tg.fillStyle = fg; tg.fillRect(Math.round(px) - 1, trackY - 3, 2, trackH + 6);
    if (tlHover >= 0) { tg.fillStyle = fg; tg.globalAlpha = .4; tg.fillRect(Math.round(tlHover), trackY, 1, trackH); tg.globalAlpha = 1; }
  }
  function roundRect(g, x, y, w, h, r) {
    g.beginPath(); g.moveTo(x + r, y); g.lineTo(x + w - r, y); g.quadraticCurveTo(x + w, y, x + w, y + r);
    g.lineTo(x + w, y + h - r); g.quadraticCurveTo(x + w, y + h, x + w - r, y + h); g.lineTo(x + r, y + h);
    g.quadraticCurveTo(x, y + h, x, y + h - r); g.lineTo(x, y + r); g.quadraticCurveTo(x, y, x + r, y); g.closePath();
  }
  function timeAtX(clientX) {
    const r = tlc.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * (job ? job.total : 0);
  }
  let dragging = false;
  $('tl').addEventListener('pointerdown', (e) => { if (!job) return; dragging = true; $('tl').setPointerCapture(e.pointerId); seek(timeAtX(e.clientX)); });
  $('tl').addEventListener('pointermove', (e) => {
    if (!job) return;
    const r = tlc.getBoundingClientRect(); tlHover = e.clientX - r.left;
    const t = timeAtX(e.clientX);
    if (dragging) seek(t);
    const k = C.moveAt(job, t), L = job.layer[k], so = job.layers[0] && job.layers[0].start ? 1 : 0;
    const ev = job.events.find(ev => Math.abs(((ev.move < job.moves ? job.t0[ev.move] : job.total) - t) / job.total * r.width) < 6);
    const tip = $('tip'); tip.style.display = 'block'; tip.style.left = Math.max(60, Math.min(r.width - 60, tlHover)) + 'px';
    tip.textContent = fmtTime(t) + '  ·  ' + (job.layers[L] && job.layers[L].start ? 'start' : 'layer ' + (L + 1 - so)) + (ev ? '  ·  ' + ev.label : '');
    drawTimeline();
  });
  $('tl').addEventListener('pointerup', () => { dragging = false; });
  $('tl').addEventListener('pointerleave', () => { tlHover = -1; $('tip').style.display = 'none'; drawTimeline(); });

  /* ------------------------------------------------------------------ transport */
  function seek(t) {
    if (!job) return;
    simT = Math.max(0, Math.min(job.total, t));
    updateScene(true); updateHud();
  }
  function setPlaying(p) {
    if (!job) p = false;
    if (p && simT >= job.total - 1e-6) simT = 0;
    playing = p; lastFrame = performance.now();
    $('playIco').innerHTML = p ? '<rect x="6.5" y="5" width="4" height="14" rx="1"/><rect x="13.5" y="5" width="4" height="14" rx="1"/>'
                               : '<path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.4-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/>';
  }
  function stepMove(dir) {
    if (!job) return; setPlaying(false);
    let k = C.moveAt(job, simT);
    if (dir > 0) { k++; while (k < job.moves - 1 && job.dur[k] <= 0) k++; seek(k < job.moves ? job.t0[k] + job.dur[k] : job.total); }
    else { const atStart = simT - job.t0[k] < 1e-6; k = atStart ? k - 1 : k; while (k > 0 && job.dur[k] <= 0) k--; seek(Math.max(0, job.t0[Math.max(0, k)])); }
  }
  function stepLayer(dir) {
    if (!job) return;
    // layer steps land on the end of a layer, so the layer is shown complete
    const L = job.layer[C.moveAt(job, simT)];
    const endOf = (i) => Math.max(job.layers[i].t0, job.layers[i].t1 - 1e-4);
    if (dir > 0) {
      if (simT < endOf(L) - 1e-3) seek(endOf(L));
      else seek(L + 1 < job.layers.length ? endOf(L + 1) : job.total);
    } else seek(L > 0 ? endOf(L - 1) : 0);
  }
  function gotoLayer(num) {
    if (!job) return;
    const so = job.layers[0] && job.layers[0].start ? 1 : 0;
    const i = Math.max(0, Math.min(job.layers.length - 1, num - 1 + so));
    seek(job.layers[i].t1 - 1e-6);
  }
  $('play').onclick = () => setPlaying(!playing);
  $('bStart').onclick = () => { setPlaying(false); seek(0); };
  $('bEnd').onclick = () => { setPlaying(false); seek(job ? job.total : 0); };
  $('bPrevM').onclick = () => stepMove(-1);
  $('bNextM').onclick = () => stepMove(1);
  $('bPrevL').onclick = () => stepLayer(-1);
  $('bNextL').onclick = () => stepLayer(1);
  $('layerIn').addEventListener('change', () => gotoLayer(parseInt($('layerIn').value, 10) || 1));
  /* Playback speed: presets, or any multiplier typed into the custom box (0.01× – 10000×). */
  const presetSpeeds = () => [...$('speedSel').options].map(o => parseFloat(o.value)).filter(v => isFinite(v));
  const fmtSpeed = (v) => (Math.round(v * 1000) / 1000) + '×';
  function showSpeed() {
    const isPreset = presetSpeeds().some(v => Math.abs(v - prefs.speed) < 1e-9);
    $('speedSel').value = isPreset ? String(presetSpeeds().find(v => Math.abs(v - prefs.speed) < 1e-9)) : 'custom';
    $('speedCustomWrap').hidden = isPreset;
    if (!isPreset && document.activeElement !== $('speedCustom')) $('speedCustom').value = prefs.speed;
  }
  function setSpeed(v, announce) {
    if (!isFinite(v) || v <= 0) return;
    prefs.speed = Math.min(10000, Math.max(0.01, v)); savePrefs(); showSpeed();
    if (announce) toast('Playback ' + fmtSpeed(prefs.speed));
  }
  $('speedSel').onchange = () => {
    if ($('speedSel').value === 'custom') {
      $('speedCustomWrap').hidden = false; $('speedCustom').value = prefs.speed; $('speedCustom').focus(); $('speedCustom').select();
    } else setSpeed(parseFloat($('speedSel').value));
  };
  $('speedCustom').addEventListener('change', () => setSpeed(parseFloat($('speedCustom').value)));
  $('speedCustom').addEventListener('keydown', (e) => { if (e.key === 'Enter') { setSpeed(parseFloat($('speedCustom').value)); $('speedCustom').blur(); } });
  function bumpSpeed(dir) {
    // the next preset above (or below) the current speed, custom values included
    const opts = presetSpeeds().sort((p, q) => p - q);
    const next = dir > 0 ? opts.find(v => v > prefs.speed + 1e-9) : [...opts].reverse().find(v => v < prefs.speed - 1e-9);
    if (next != null) setSpeed(next, true);
  }

  document.addEventListener('keydown', (e) => {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT')) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    switch (e.key) {
      case ' ': e.preventDefault(); setPlaying(!playing); break;
      case 'ArrowRight': e.preventDefault(); stepMove(1); break;
      case 'ArrowLeft': e.preventDefault(); stepMove(-1); break;
      case 'ArrowUp': e.preventDefault(); stepLayer(1); break;
      case 'ArrowDown': e.preventDefault(); stepLayer(-1); break;
      case 'Home': setPlaying(false); seek(0); break;
      case 'End': setPlaying(false); seek(job ? job.total : 0); break;
      case '+': case '=': bumpSpeed(1); break;
      case '-': case '_': bumpSpeed(-1); break;
      case 't': case 'T': toggle('travel', $('tTravel')); break;
      case 'l': case 'L': toggle('layerOnly', $('tLayer')); break;
      case 'f': case 'F': toggle('follow', $('tFollow')); break;
      case 'g': case 'G': setCodeOpen(!codeOpen); break;
    }
  });

  /* ------------------------------------------------------------------ options */
  function toggle(key, btn) { prefs[key] = !prefs[key]; btn.classList.toggle('on', prefs[key]); savePrefs(); updateScene(true); }
  function syncOptionUI() {
    $('tTravel').classList.toggle('on', prefs.travel); $('tLayer').classList.toggle('on', prefs.layerOnly);
    $('tFollow').classList.toggle('on', prefs.follow);
    $('colorSel').value = prefs.color; $('motionSel').value = prefs.motion; $('lineSel').value = prefs.lines;
    $('timingSel').value = prefs.timing; showSpeed();
    $('pauseLeaveChk').checked = prefs.pauseOnLeave !== false;
    $('headChk').checked = prefs.head !== false; $('gantryChk').checked = prefs.gantry !== false;
    $('shadeSel').value = prefs.shade || 'tube';
    headGroup.visible = prefs.head !== false; gantry.visible = prefs.gantry !== false;
  }
  $('optBtn').onclick = (e) => { e.stopPropagation(); $('optPanel').hidden = !$('optPanel').hidden; $('optBtn').classList.toggle('on', !$('optPanel').hidden); };
  document.addEventListener('pointerdown', (e) => {
    if (!$('optPanel').hidden && !$('optPanel').contains(e.target) && e.target !== $('optBtn') && !$('optBtn').contains(e.target)) {
      $('optPanel').hidden = true; $('optBtn').classList.remove('on');
    }
  });
  (function about() {
    const info = window.PLAYBACK_ABOUT; if (!info) return;
    $('verText').textContent = 'Real G-code Playback v' + info.version;
    const esc = (t) => String(t).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
    $('changelog').innerHTML = info.entries.map(e => '<h5>v' + esc(e.version) + ' <span>' + esc(e.date || '') + '</span></h5><ul>' +
      e.changes.map(c => '<li>' + esc(c) + '</li>').join('') + '</ul>').join('');
    $('logLink').onclick = (ev) => { ev.preventDefault(); $('changelog').hidden = !$('changelog').hidden; };
  })();
  /* Print options found in this G-code (Bambu conditional blocks). Changing one re-reads the file
     with the new choice and keeps the playback position. */
  function renderFlags() {
    const box = $('flagList');
    const found = job && job.flagsFound ? job.flagsFound : [];
    box.hidden = !found.length;
    if (!found.length) { box.innerHTML = ''; return; }
    const esc = (t) => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    box.innerHTML = '<div class="flagHead">Print options in this G-code</div>' + found.map(f =>
      '<label class="check" title="' + esc(f.name) + '"><input type="checkbox" data-flag="' + esc(f.name) + '"' + (f.value ? ' checked' : '') + '> ' +
      esc(f.label) + (f.count > 1 ? ' <span class="muted">×' + f.count + '</span>' : '') + '</label>').join('') +
      '<div class="flagNote">Choose them as you will when sending the print. Heating time is not counted.</div>';
    box.querySelectorAll('input[data-flag]').forEach(inp => inp.onchange = () => {
      prefs.flags = Object.assign({}, prefs.flags, { [inp.dataset.flag]: inp.checked }); savePrefs();
      reparse();
    });
  }
  async function reparse() {
    if (!job || !gcodeText) return;
    const frac = simT / Math.max(1e-9, job.total), wasPlaying = playing, before = job.total;
    await loadText(gcodeText, Object.assign({}, currentMeta, { keepFrac: frac, keepView: true }));
    if (job) toast('Print time ' + (job.total < before ? '−' : '+') + fmtLong(Math.abs(job.total - before)) + ' → ' + fmtLong(job.total));
    if (wasPlaying) setPlaying(true);
  }
  $('pauseLeaveChk').onchange = () => { prefs.pauseOnLeave = $('pauseLeaveChk').checked; savePrefs(); };
  $('headChk').onchange = () => { prefs.head = $('headChk').checked; headGroup.visible = prefs.head; savePrefs(); dirty = true; };
  $('gantryChk').onchange = () => { prefs.gantry = $('gantryChk').checked; gantry.visible = prefs.gantry; savePrefs(); dirty = true; };
  $('shadeSel').onchange = () => { prefs.shade = $('shadeSel').value; savePrefs(); recolor(); };
  $('tTravel').onclick = () => toggle('travel', $('tTravel'));
  $('tLayer').onclick = () => toggle('layerOnly', $('tLayer'));
  $('tFollow').onclick = () => toggle('follow', $('tFollow'));
  function recolor() {
    if (!job) return;
    computeColors();
    if (R.main.userData.thin) R.main.geometry.attributes.color.needsUpdate = true; else R.main.geometry.setColors(R.col);
    R.layerObjLayer = -1; updateScene(true);
  }
  $('colorSel').onchange = () => { prefs.color = $('colorSel').value; savePrefs(); recolor(); };
  $('motionSel').onchange = () => { prefs.motion = $('motionSel').value; savePrefs(); updateScene(true); };
  $('lineSel').onchange = () => { prefs.lines = $('lineSel').value; savePrefs(); if (job) { rebuildObjects(); updateScene(true); } };
  $('timingSel').onchange = () => {
    prefs.timing = $('timingSel').value; savePrefs();
    if (!job) return;
    const frac = simT / job.total;
    C.applyTiming(job, prefs.timing === 'aligned');
    simT = frac * job.total; describeTiming();
    if (prefs.color === 'layertime') { computeColors(); if (R.main.userData.thin) R.main.geometry.attributes.color.needsUpdate = true; else R.main.geometry.setColors(R.col); }
    updateScene(true); updateHud();
  };

  /* ------------------------------------------------------------------ camera */
  function frame(view) {
    if (!job) return;
    const m = job.bed.model, bed = job.bed;
    const cx = (m.minX + m.maxX) / 2, cy = (m.minY + m.maxY) / 2, cz = (m.minZ + m.maxZ) / 2;
    const size = Math.max(m.maxX - m.minX, m.maxY - m.minY, m.maxZ - m.minZ, 20);
    const yOff = bedSlinger() ? bedGroup.position.y : 0;
    const target = new THREE.Vector3(cx, cy + yOff, cz);
    const d = size * 1.7 + 18;
    let dir;
    if (view === 'top') dir = new THREE.Vector3(0, -0.001, 1);
    else if (view === 'front') dir = new THREE.Vector3(0, -1, 0.12);
    else if (view === 'bed') { const s = Math.max(bed.x1 - bed.x0, bed.y1 - bed.y0); target.set((bed.x0 + bed.x1) / 2, (bed.y0 + bed.y1) / 2 + yOff, 0); dir = new THREE.Vector3(-0.55, -1, 0.8); return place(target, dir.normalize().multiplyScalar(s * 1.6)); }
    else dir = new THREE.Vector3(-0.6, -1, 0.75);
    place(target, dir.normalize().multiplyScalar(d));
  }
  function place(target, offset) {
    controls.target.copy(target); camera.position.copy(target).add(offset); camera.updateProjectionMatrix(); controls.update(); dirty = true;
  }
  $('vIso').onclick = () => frame('iso'); $('vTop').onclick = () => frame('top');
  $('vFront').onclick = () => frame('front'); $('vFit').onclick = () => frame('iso');

  function resize() {
    const r = canvas.getBoundingClientRect();
    const w = Math.max(1, r.width), h = Math.max(1, r.height);
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    if (lineMat) { lineMat.resolution.set(w, h); lineMatPartial.resolution.set(w, h); }
    dirty = true; drawTimeline();
  }
  new ResizeObserver(resize).observe($('stage'));

  function applyTheme() {
    const bg = cssVar('--bg', '#1e2023');
    scene.background = new THREE.Color(bg);
    dirty = true;
  }

  /* ------------------------------------------------------------------ main loop */
  /* Leaving the Playback tab pauses. OrcaSlicer hides the tab's web view, which the page sees as
     visibilitychange; as a second signal, a long gap between animation frames means the view was
     not being drawn (hidden), which is treated the same way. */
  let lastLoop = 0;
  function onLeave() { if (playing && prefs.pauseOnLeave !== false) setPlaying(false); }
  function onReturn() { send({ cmd: 'check_latest' }); }
  document.addEventListener('visibilitychange', () => { if (document.hidden) onLeave(); else onReturn(); });
  window.addEventListener('pagehide', onLeave);

  function loop(now) {
    requestAnimationFrame(loop);
    if (lastLoop && now - lastLoop > 1500) {
      // the view was hidden (no frames were drawn). If playback keeps going while away, catch the
      // clock up by the time spent away so the print has progressed when you come back.
      if (playing && prefs.pauseOnLeave === false && job) {
        simT = Math.min(job.total, simT + (now - lastLoop) / 1000 * prefs.speed);
        lastFrame = now; updateScene(true); updateHud();
      }
      onLeave(); onReturn();
    }
    lastLoop = now;
    if (codeOpen && job && playing) {
      const cur = job.line[curMove];
      if (cur !== codeLastCur) { codeLastCur = cur; codeFollowTo(false); renderCode(); }
    }
    stepCodeScroll();
    if (playing && job) {
      const dt = Math.min(0.25, (now - lastFrame) / 1000); lastFrame = now;
      simT += dt * prefs.speed;
      if (simT >= job.total) { simT = job.total; setPlaying(false); }
      updateScene(false);
      if (now - hudTimer > 90) { hudTimer = now; updateHud(); }
    }
    if (controls.update()) dirty = true;
    if (prefs.follow && job) dirty = true;
    if (dirty) { renderer.render(scene, camera); dirty = false; }
  }

  /* ------------------------------------------------------------------ loading */
  async function loadText(text, meta) {
    meta = meta || {};
    setPlaying(false);
    busy('Reading G-code…', 0); await nextFrame();
    let parsed;
    try {
      parsed = C.parseGcode(text, { flags: prefs.flags || {}, progress: (f) => { $('busyBar').style.width = Math.round(f * 85) + '%'; } });
      busy('Planning motion…', 0.88); await nextFrame();
      C.planJob(parsed, { align: prefs.timing === 'aligned' });
    } catch (err) {
      busy(null); toast('Could not read this G-code: ' + err.message, true); console.error(err); return false;
    }
    if (parsed.moves < 2) { busy(null); toast('No moves found in this file.', true); return false; }
    job = parsed; gcodeText = text; lineStarts = null; codeLastCur = -1; currentMeta = meta;
    if (codeOpen) { codeScroll.scrollTop = 0; }
    busy('Building paths…', 0.95); await nextFrame();
    for (const k in featVisible) delete featVisible[k];
    buildBed(job.bed);
    buildPaths();
    $('empty').style.display = 'none';
    $('hud').hidden = false; $('viewbtns').hidden = false; $('legend').hidden = false;
    $('fileName').textContent = meta.name || 'G-code';
    const so = job.layers[0] && job.layers[0].start ? 1 : 0;
    $('fileInfo').textContent = (job.layers.length - so) + ' layers · ' + (job.moves / 1000).toFixed(job.moves > 1e5 ? 0 : 1) + 'k moves' +
      (meta.when ? ' · ' + meta.when : '');
    $('layerIn').max = job.layers.length - so;
    describeTiming();
    if (R.segMove.length > 1200000 && prefs.lines === 'fat')
      setTimeout(() => toast('Large print (' + Math.round(R.segMove.length / 1e5) / 10 + 'M lines). If playback stutters, use Options → Line style → Thin lines.'), 400);
    simT = meta.keepFrac != null ? meta.keepFrac * job.total : meta.keepTime != null ? Math.min(meta.keepTime, job.total) : 0;
    if (!meta.keepView) frame('iso');
    renderFlags();
    updateScene(true); updateHud();
    busy(null);
    return true;
  }
  function describeTiming() {
    const b = $('timingBadge'); b.hidden = false;
    if (job.aligned) {
      const adjusted = Math.abs(job.total - job.estimate) > 1;
      b.className = 'badge ok'; b.textContent = (adjusted ? 'Synced to slicer, adjusted for print options · ' : 'Synced to slicer · ') + fmtLong(job.total);
      b.title = 'Total time matches the slicer estimate (' + fmtLong(job.estimate) + '); the motion planner fills in the timing between its progress markers. Planner alone: ' + fmtLong(job.plannerTotal) + '.';
    } else {
      b.className = 'badge'; b.textContent = 'Planner estimate · ' + fmtLong(job.total);
      b.title = job.estimate ? 'Slicer estimate: ' + fmtLong(job.estimate) + '. Choose "match slicer estimate" to sync to it.'
                             : 'No slicer estimate in this file; times come from the built-in motion planner.';
    }
  }

  /* --- files: .gcode and .gcode.3mf (zip) */
  async function readZipGcodes(buf) {
    const dv = new DataView(buf), u8 = new Uint8Array(buf);
    let eocd = -1;
    for (let i = u8.length - 22; i >= Math.max(0, u8.length - 65557); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new Error('not a zip / 3MF file');
    const count = dv.getUint16(eocd + 10, true); let p = dv.getUint32(eocd + 16, true);
    const td = new TextDecoder(); const out = [];
    for (let i = 0; i < count; i++) {
      if (dv.getUint32(p, true) !== 0x02014b50) break;
      const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true);
      const nlen = dv.getUint16(p + 28, true), xlen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true);
      const lho = dv.getUint32(p + 42, true);
      const name = td.decode(u8.subarray(p + 46, p + 46 + nlen));
      p += 46 + nlen + xlen + clen;
      if (!/\.gcode$/i.test(name)) continue;
      const lnl = dv.getUint16(lho + 26, true), lxl = dv.getUint16(lho + 28, true);
      const data = u8.subarray(lho + 30 + lnl + lxl, lho + 30 + lnl + lxl + csize);
      out.push({ name, method, data });
    }
    return out;
  }
  async function inflate(entry) {
    if (entry.method === 0) return new TextDecoder().decode(entry.data);
    if (entry.method !== 8) throw new Error('unsupported compression in 3MF');
    if (typeof DecompressionStream === 'undefined') throw new Error('this viewer cannot unzip 3MF files; export plain G-code instead');
    const stream = new Blob([entry.data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return await new Response(stream).text();
  }
  let pendingPlates = null;
  async function openFile(file) {
    try {
      busy('Opening ' + file.name + '…', 0.02); await nextFrame();
      if (/\.3mf$/i.test(file.name)) {
        const entries = await readZipGcodes(await file.arrayBuffer());
        if (!entries.length) { busy(null); toast('This 3MF has no sliced G-code. Use a .gcode.3mf exported after slicing.', true); return; }
        pendingPlates = { file: file.name, entries };
        const sel = $('plateSel');
        sel.innerHTML = entries.map((e, i) => '<option value="' + i + '">' + (/plate_(\d+)/i.exec(e.name) ? 'Plate ' + /plate_(\d+)/i.exec(e.name)[1] : e.name) + '</option>').join('');
        sel.hidden = entries.length < 2;
        await loadPlate(0);
      } else {
        $('plateSel').hidden = true; pendingPlates = null;
        if (await loadText(await file.text(), { name: file.name, when: 'opened file' })) loadedStamp = null;
      }
    } catch (err) { busy(null); toast(err.message, true); }
  }
  async function loadPlate(i) {
    const e = pendingPlates.entries[i];
    busy('Unpacking ' + e.name + '…', 0.05); await nextFrame();
    await loadText(await inflate(e), { name: pendingPlates.file + (pendingPlates.entries.length > 1 ? ' · plate ' + (i + 1) : ''), when: 'opened file' });
  }
  $('plateSel').onchange = () => { if (pendingPlates) loadPlate(parseInt($('plateSel').value, 10)); };
  $('btnOpen').onclick = $('eOpen').onclick = () => $('file-in').click();
  $('file-in').onchange = () => { const f = $('file-in').files[0]; if (f) openFile(f); $('file-in').value = ''; };
  let dragDepth = 0;
  window.addEventListener('dragenter', (e) => { e.preventDefault(); dragDepth++; $('drop').style.display = 'grid'; });
  window.addEventListener('dragleave', (e) => { e.preventDefault(); if (--dragDepth <= 0) { dragDepth = 0; $('drop').style.display = 'none'; } });
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => {
    e.preventDefault(); dragDepth = 0; $('drop').style.display = 'none';
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]; if (f) openFile(f);
  });

  /* --- from the plugin: the latest slice, sent in chunks */
  let incoming = null;
  function requestLatest(quiet) {
    if (!host) { toast('Latest slice is only available inside OrcaSlicer.', true); return; }
    hideNewSlice();
    busy('Fetching the latest slice…', 0.02);
    send({ cmd: 'load_latest', quiet: !!quiet });
  }
  /* A newer slice than the one shown: load it if nothing is shown yet, otherwise ask. */
  let loadedStamp = null, dismissedStamp = null, offeredStamp = null;
  function considerLatest(latest) {
    if (!latest || !latest.stamp) return;
    if (latest.stamp === loadedStamp || latest.stamp === dismissedStamp) return;
    if (incoming || $('busy').style.display === 'grid') return;
    if (!job) { requestLatest(true); return; }
    offeredStamp = latest.stamp;
    $('newSliceWhen').textContent = latest.when ? '· ' + latest.when : '';
    $('newSlice').hidden = false;
  }
  function hideNewSlice() { $('newSlice').hidden = true; }
  $('nsLoad').onclick = () => requestLatest(false);
  $('nsKeep').onclick = () => { dismissedStamp = offeredStamp; hideNewSlice(); };
  $('btnLatest').onclick = $('eLatest').onclick = () => requestLatest(false);
  $('btnLatest').disabled = !host; $('eLatest').disabled = !host;

    function onHostMessage(msg) {
    if (!msg || typeof msg !== 'object') return;
    switch (msg.cmd) {
      case 'status': {
        if (msg.prefs && typeof msg.prefs === 'object') { Object.assign(prefs, msg.prefs); syncOptionUI(); }
        renderSetup(msg);
        considerLatest(msg.latest);
        break;
      }
      case 'latest_info':
        renderSetup(msg);
        if (!document.hidden) considerLatest(msg.latest);
        break;
      case 'slice_ready':
        // sliced while this tab is hidden: nothing to do now, the check runs when the tab is shown
        renderSetup(msg);
        if (!document.hidden) considerLatest(msg.latest);
        break;
      case 'gcode_begin':
        incoming = { id: msg.id, name: msg.name, size: msg.size, when: msg.when, stamp: msg.stamp, parts: new Array(msg.chunks), got: 0 };
        busy('Receiving ' + (msg.name || 'G-code') + '…', 0.02);
        break;
      case 'gcode_chunk':
        if (!incoming || msg.id !== incoming.id) break;
        incoming.parts[msg.i] = msg.data; incoming.got++;
        $('busyBar').style.width = Math.round(incoming.got / incoming.parts.length * 40) + '%';
        break;
      case 'gcode_end': {
        if (!incoming || msg.id !== incoming.id) break;
        const inc = incoming; incoming = null;
        if (inc.got !== inc.parts.length) { busy(null); toast('The G-code transfer was incomplete; try again.', true); break; }
        $('plateSel').hidden = true; pendingPlates = null;
        loadText(inc.parts.join(''), { name: inc.name, when: inc.when }).then((ok) => { if (ok) { loadedStamp = inc.stamp || null; hideNewSlice(); } });
        break;
      }
      case 'error':
        busy(null); if (!msg.quiet) toast(msg.message || 'Something went wrong', true);
        if (msg.stamp) dismissedStamp = msg.stamp;     // don't retry the same failing slice on every visit
        if (msg.setup) renderSetup(msg);
        break;
      case 'toast': toast(msg.message); break;
    }
  }
  function renderSetup(msg) {
    const steps = $('setupSteps');
    if (msg.capture_enabled === false && msg.hint) {
      steps.hidden = false;
      // numbered rows built by hand: a native <ol> picks up the host page's list styles in OrcaSlicer
      steps.innerHTML = '<div class="title">' + msg.hint.title + '</div>' +
        msg.hint.steps.map((t, i) => '<div class="step"><span class="num">' + (i + 1) + '</span><span class="txt">' + t + '</span></div>').join('');
    } else steps.hidden = true;
  }
  if (host) host.onMessage(onHostMessage);

  /* ------------------------------------------------------------------ boot */
  syncOptionUI();
  applyTheme();
  if (window.matchMedia) window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);
  resize();
  requestAnimationFrame(loop);
  send({ cmd: 'hello' });
  // test hook: standalone page can be driven from the console / a harness
  window.PlaybackApp = { loadText, seek, setPlaying, get job() { return job; }, get time() { return simT; },
                         setPrefs(p) { Object.assign(prefs, p); syncOptionUI(); if (job) { rebuildObjects(); computeColors(); if (R.main.userData.thin) R.main.geometry.attributes.color.needsUpdate = true; else R.main.geometry.setColors(R.col); updateScene(true); updateHud(); } },
                         frame, onHostMessage };
})();
