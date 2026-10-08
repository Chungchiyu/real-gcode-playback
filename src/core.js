/* Playback core: G-code parser + motion planner. Pure JS, no DOM, so it runs in node for tests.
 *
 * parseGcode(text, opts) -> Job
 *   Job.moves        number of moves (move i goes from point i to point i+1)
 *   Job.pts          Float32Array, (moves+1)*3 xyz
 *   Job.flags        Uint8Array   FL_* bits per move
 *   Job.feat         Uint8Array   feature id per move (see FEATURES)
 *   Job.layer        Uint32Array  layer index per move
 *   Job.tool         Uint8Array   tool / filament index per move
 *   Job.fcmd         Float32Array commanded feedrate (mm/s)
 *   Job.len          Float32Array path length (mm; E length for E-only moves)
 *   Job.de           Float32Array extruder delta (mm of filament)
 *   Job.acc          Float32Array acceleration in force for the move (mm/s^2)
 *   Job.wait         Float32Array fixed duration for dwell pseudo-moves (s)
 *   Job.line         Uint32Array  1-based source line number
 *   Job.layers       [{z, h, first}]   first = first move index of the layer
 *   Job.events       [{move, kind, label}]
 *   Job.m73          [{move, p}]        Orca/Bambu progress markers (percent of time)
 *   Job.config       {key: value}       slicer config found in comments
 *   Job.estimate     seconds | 0        slicer's own total estimate from the header
 *   Job.machine      resolved machine limits used by the planner
 *
 * planJob(job, {align}) adds timing:
 *   Job.t0   Float64Array start time per move (aligned to the slicer estimate when available)
 *   Job.dur  Float32Array duration per move (aligned)
 *   Job.vi / vp / vf / ac  trapezoid (entry, peak, exit, accel) in planner time
 *   Job.total total time, Job.plannerTotal raw planner total, Job.aligned bool
 */
(function (root) {
  'use strict';

  const FL_EXTRUDE = 1, FL_TRAVEL = 2, FL_EONLY = 4, FL_DWELL = 8, FL_ARC = 16, FL_STOP = 32, FL_SKIP = 64;

  /* Bambu-style conditional blocks: `M1002 judge_flag NAME` + `M622 J1|J0` … `M623`. The printer decides
     at print time from the options chosen when sending; the viewer lets the user choose instead.
     Defaults follow the usual send-dialog choices; anything else uses the file's own M622.1 default. */
  const FLAG_INFO = {
    g29_before_print_flag: { label: 'Bed leveling', def: true },
    extrude_cali_flag: { label: 'Flow dynamics calibration', def: true },
    timelapse_record_flag: { label: 'Timelapse', def: false },
    build_plate_detect_flag: { label: 'Build plate detection', def: true },
    g39_3rd_layer_detect_flag: { label: 'Nozzle clumping detection (layer 3)' },
    g39_detection_flag: { label: 'Nozzle clumping detection' },
    g39_mass_exceed_flag: { label: 'Clumping check: mass exceeded' },
    filament_need_cali_flag: { label: 'Calibrate after filament change' },
    last_extrude_cali_success: { label: 'Last flow calibration succeeded', def: true },
  };
  function flagLabel(name) { return (FLAG_INFO[name] && FLAG_INFO[name].label) || name.replace(/_flag$/, '').replace(/_/g, ' '); }

  // Canonical features. Colours follow OrcaSlicer's preview defaults so the two views read alike.
  const FEATURES = [
    ['Other', '#9aa3ab'],
    ['Inner wall', '#ffe64d'],
    ['Outer wall', '#ff7d38'],
    ['Overhang wall', '#0000ff'],
    ['Sparse infill', '#b03029'],
    ['Internal solid infill', '#9654cc'],
    ['Top surface', '#f04040'],
    ['Bottom surface', '#669999'],
    ['Bridge', '#4d80ba'],
    ['Gap infill', '#ffffff'],
    ['Skirt', '#00876e'],
    ['Brim', '#00876e'],
    ['Support', '#00ff00'],
    ['Support interface', '#008000'],
    ['Support transition', '#004000'],
    ['Prime tower', '#b3e3ab'],
    ['Ironing', '#ff8c69'],
    ['Custom', '#5ed194'],
    ['Flush / purge', '#c7a26b'],
  ];
  const FEAT_INDEX = {};
  FEATURES.forEach((f, i) => { FEAT_INDEX[f[0].toLowerCase()] = i; });
  const FEAT_ALIASES = {
    'perimeter': 1, 'internal perimeter': 1, 'inner wall': 1,
    'external perimeter': 2, 'outer wall': 2,
    'overhang perimeter': 3, 'overhang wall': 3,
    'internal infill': 4, 'sparse infill': 4, 'infill': 4, 'fill': 4,
    'solid infill': 5, 'internal solid infill': 5,
    'top solid infill': 6, 'top surface': 6, 'top': 6,
    'bottom surface': 7, 'bottom solid infill': 7, 'bottom': 7,
    'bridge infill': 8, 'bridge': 8, 'internal bridge': 8, 'internal bridge infill': 8,
    'gap fill': 9, 'gap infill': 9, 'gapfill': 9,
    'skirt': 10, 'skirt/brim': 10, 'brim': 11,
    'support': 12, 'support material': 12,
    'support interface': 13, 'support material interface': 13,
    'support transition': 14,
    'prime tower': 15, 'wipe tower': 15,
    'ironing': 16,
    'custom': 17,
  };
  function featureId(name) {
    const k = String(name || '').trim().toLowerCase();
    if (k in FEAT_ALIASES) return FEAT_ALIASES[k];
    if (k in FEAT_INDEX) return FEAT_INDEX[k];
    if (k.indexOf('support') >= 0) return k.indexOf('interface') >= 0 ? 13 : 12;
    if (k.indexOf('wall') >= 0 || k.indexOf('perimeter') >= 0) return 1;
    if (k.indexOf('infill') >= 0) return 4;
    if (k.indexOf('tower') >= 0) return 15;
    return 0;
  }

  /* ---------------------------------------------------------------- growable typed arrays */
  function Grow(Type, cap) { this.T = Type; this.a = new Type(cap); this.n = 0; }
  Grow.prototype.ensure = function (n) {
    if (n <= this.a.length) return;
    let c = this.a.length * 2; while (c < n) c *= 2;
    const b = new this.T(c); b.set(this.a); this.a = b;
  };
  Grow.prototype.out = function (n) { return this.a.slice(0, n); };

  /* ---------------------------------------------------------------- helpers */
  function num(v, d) { const x = parseFloat(v); return isFinite(x) ? x : d; }
  function first(v, d) {           // "500,200" -> 500 ; "[500, 200]" -> 500
    if (v == null) return d;
    const s = String(v).replace(/[\[\]"']/g, '').split(/[,;]/)[0];
    return num(s, d);
  }
  function parseDuration(s) {      // "1d 2h 3m 4s" / "2h3m" / "45s"
    if (!s) return 0;
    let t = 0, hit = false; const re = /(\d+(?:\.\d+)?)\s*([dhms])/gi; let m;
    while ((m = re.exec(s))) { hit = true; t += parseFloat(m[1]) * ({ d: 86400, h: 3600, m: 60, s: 1 })[m[2].toLowerCase()]; }
    return hit ? t : 0;
  }

  /* ---------------------------------------------------------------- parser */
  function parseGcode(text, opts) {
    opts = opts || {};
    const progress = opts.progress || null;
    const est = Math.max(1024, (text.length / 30) | 0);
    const P = new Grow(Float32Array, (est + 1) * 3);
    const G = {
      flags: new Grow(Uint8Array, est), feat: new Grow(Uint8Array, est), layer: new Grow(Uint32Array, est),
      tool: new Grow(Uint8Array, est), fcmd: new Grow(Float32Array, est), len: new Grow(Float32Array, est),
      de: new Grow(Float32Array, est), acc: new Grow(Float32Array, est), wait: new Grow(Float32Array, est),
      line: new Grow(Uint32Array, est),
    };
    let n = 0;                                   // move count
    const config = {}; const layers = []; const events = []; const m73 = [];
    let estimate = 0, estimateSilent = 0;

    // machine state
    let x = 0, y = 0, z = 0, e = 0;              // logical (G92-adjusted) coordinates
    let ox = 0, oy = 0, oz = 0;                   // G92 offsets for xyz
    let absXYZ = true, absE = true, fmm = 3000 / 60; // feed in mm/s
    let accPrint = 0, accTravel = 0, accRetract = 0;  // filled from config after the scan
    let curFeat = 0, curTool = 0, curLayer = 0;
    // Slicer layer markers, when present, are the truth; otherwise layers are inferred from Z.
    let haveLayerComments = /^;\s*(LAYER_CHANGE|CHANGE_LAYER)\s*$/m.test(text.length > 4e6 ? text.substring(0, 4e6) : text);
    let lastExtrudeZ = -1e9, lastExtrudeMove = 0;
    if (haveLayerComments) layers.push({ z: 0, h: 0, first: 0, start: true });   // start G-code, before layer 1
    let pendingStop = false;                     // a blocking command happened since the last move
    // conditional blocks
    const flagChoices = opts.flags || {};
    const flagsFound = {};                       // name -> { name, label, value, fileDefault, count }
    const blockStack = [];                       // true = this block runs
    let judged = true, nextDefault = null, skipping = false, saved = null, g29Window = false, skippedMoves = 0;
    const isBambu = text.indexOf('M1002 ') >= 0 || text.indexOf('M622 ') >= 0;
    function judge(name) {
      let def = nextDefault != null ? nextDefault : (FLAG_INFO[name] && FLAG_INFO[name].def != null ? FLAG_INFO[name].def : true);
      if (FLAG_INFO[name] && FLAG_INFO[name].def != null) def = FLAG_INFO[name].def;
      const value = name in flagChoices ? !!flagChoices[name] : def;
      const f = flagsFound[name] || (flagsFound[name] = { name, label: flagLabel(name), value, fileDefault: def, count: 0 });
      f.count++;
      nextDefault = null; judged = value;
    }
    function updateSkipping() {
      const now = blockStack.some(b => !b);
      if (now && !skipping) {
        // entering a block the printer will not run: remember the real machine state
        saved = { x, y, z, e, ox, oy, oz, absXYZ, absE, fmm, accPrint, accTravel, accRetract, curFeat, curTool,
                  px: P.a[n * 3], py: P.a[n * 3 + 1], pz: P.a[n * 3 + 2] };
        pendingStop = true;
      } else if (!now && skipping && saved) {
        // leaving it: put the head back where it really is (a zero-time, undrawn hop)
        const hx = P.a[n * 3], hy = P.a[n * 3 + 1], hz = P.a[n * 3 + 2];
        if (hx !== saved.px || hy !== saved.py || hz !== saved.pz) {
          const L = Math.hypot(saved.px - hx, saved.py - hy, saved.pz - hz);
          skipping = true; push(saved.px, saved.py, saved.pz, FL_TRAVEL, 0, fmm, L, 0, lineNo);
        }
        ({ x, y, z, e, ox, oy, oz, absXYZ, absE, fmm, accPrint, accTravel, accRetract, curFeat, curTool } = saved);
        saved = null; pendingStop = true;
      }
      skipping = now;
    }
    function addEvent(ev) { if (!skipping) events.push(ev); }
    const machineCmd = {};                       // limits set by M201/M203/M205/SET_VELOCITY_LIMIT

    P.ensure(3); P.a[0] = 0; P.a[1] = 0; P.a[2] = 0;
    let started = false;                         // first real XY position seen

    function push(nx, ny, nz, flags, dE, fcmd, length, waitS, lineNo) {
      if (n + 1 >= G.flags.a.length) for (const k in G) G[k].ensure(n + 2);
      P.ensure((n + 2) * 3);
      const p = (n + 1) * 3; P.a[p] = nx; P.a[p + 1] = ny; P.a[p + 2] = nz;
      if (pendingStop) { flags |= FL_STOP; pendingStop = false; }
      if (skipping) { flags |= FL_SKIP; skippedMoves++; }
      G.flags.a[n] = flags; G.feat.a[n] = curFeat; G.layer.a[n] = curLayer < 0 ? 0 : curLayer;
      G.tool.a[n] = curTool; G.fcmd.a[n] = fcmd; G.len.a[n] = length; G.de.a[n] = dE;
      G.acc.a[n] = (flags & FL_EXTRUDE) ? accPrint : (flags & FL_EONLY) ? (accRetract || accPrint) : (accTravel || accPrint);
      G.wait.a[n] = waitS; G.line.a[n] = lineNo;
      n++;
    }
    function startLayer(zv, hv) {
      curLayer = layers.length;
      layers.push({ z: zv, h: hv || 0, first: n });
    }
    function phys(i) { return P.a[n * 3 + i]; }

    function linearMove(tx, ty, tz, dE, lineNo, arcFlag) {
      const cx = phys(0), cy = phys(1), cz = phys(2);
      const dx = tx - cx, dy = ty - cy, dz = tz - cz;
      const L = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (L < 1e-6) {
        if (Math.abs(dE) > 1e-7) push(cx, cy, cz, FL_EONLY, dE, fmm, Math.abs(dE), 0, lineNo);
        return;
      }
      let fl = (dE > 1e-7 && (dx * dx + dy * dy) > 1e-12) ? FL_EXTRUDE : FL_TRAVEL;
      if (arcFlag) fl |= FL_ARC;
      if (fl & FL_EXTRUDE) {
        // a layer is wherever extrusion happens at a new height, when the slicer gave us no markers
        if (!skipping) {
          if (!haveLayerComments && tz > lastExtrudeZ + 0.015) { startLayer(tz, layers.length ? tz - lastExtrudeZ : tz); }
          lastExtrudeZ = Math.max(lastExtrudeZ, tz); lastExtrudeMove = n + 1;
        }
      }
      push(tx, ty, tz, fl, dE, fmm, L, 0, lineNo);
    }

    let i = 0, lineNo = 0; const len = text.length;
    let nextReport = 200000;
    const word = { G: NaN, M: NaN, X: NaN, Y: NaN, Z: NaN, E: NaN, F: NaN, I: NaN, J: NaN, R: NaN, P: NaN, S: NaN, T: NaN, L: NaN };

    while (i < len) {
      let j = text.indexOf('\n', i); if (j < 0) j = len;
      lineNo++;
      let line = text.substring(i, j);
      i = j + 1;
      if (progress && i > nextReport) { nextReport += 200000; progress(i / len); }

      // ---- comments
      let c = line.indexOf(';');
      let comment = null;
      if (c >= 0) { comment = line.substring(c + 1); line = line.substring(0, c); }
      if (comment !== null) {
        const t = comment.trim();
        if (t.length) {
          let m;
          if ((m = /^TYPE:\s*(.+)$/.exec(t)) || (m = /^FEATURE:\s*(.+)$/.exec(t))) {
            curFeat = featureId(m[1]);
          } else if (t === 'LAYER_CHANGE' || t === 'CHANGE_LAYER') {
            if (!haveLayerComments) { haveLayerComments = true; }
            const lastL = layers[layers.length - 1];
            if (lastL && lastL.first === n) { lastL.z = phys(2); lastL.start = false; curLayer = layers.length - 1; }
            else startLayer(phys(2), 0);
          } else if ((m = /^(?:Z|Z_HEIGHT):\s*([\d.]+)/.exec(t))) {
            if (layers.length && haveLayerComments) layers[layers.length - 1].z = parseFloat(m[1]);
          } else if ((m = /^(?:HEIGHT|LAYER_HEIGHT):\s*([\d.]+)/.exec(t))) {
            if (layers.length && haveLayerComments) layers[layers.length - 1].h = parseFloat(m[1]);
          } else if ((m = /^estimated printing time \((normal|silent) mode\)\s*[=:]\s*(.+)$/i.exec(t))) {
            const d = parseDuration(m[2]);
            if (m[1].toLowerCase() === 'normal') { if (d) estimate = d; } else estimateSilent = d;
          } else if ((m = /^([A-Za-z][A-Za-z0-9_ ]*?)\s*[=:]\s*(.*)$/.exec(t))) {
            const key = m[1].trim().toLowerCase().replace(/\s+/g, '_');
            const val = m[2].trim();
            if (/^[a-z0-9_]+$/.test(key) && !(key in config)) config[key] = val;
            if (key === 'total_estimated_time' || key === 'estimated_printing_time_(normal_mode)' ||
                key === 'estimated_printing_time') { const d = parseDuration(val); if (d) estimate = d; }
            if (key === 'estimated_printing_time_(silent_mode)') estimateSilent = parseDuration(val);
            if (key === 'model_printing_time' && /total estimated time:\s*(.+)$/i.test(val)) {
              const d = parseDuration(/total estimated time:\s*(.+)$/i.exec(val)[1]); if (d) estimate = d;
            }
          } else if (t === 'FLUSH_START') { curFeat = 18; }
          else if (t === 'FLUSH_END') { curFeat = 17; }
        }
      }
      if (line.length === 0) continue;

      // ---- Klipper style commands
      const trimmed = line.trim();
      if (!trimmed) continue;
      const head = trimmed.charCodeAt(0);
      if (head !== 71 && head !== 77 && head !== 84 && head !== 103 && head !== 109 && head !== 116) { // not G/M/T
        const up = trimmed.toUpperCase();
        if (up.startsWith('SET_VELOCITY_LIMIT')) {
          let m;
          if ((m = /ACCEL=([\d.]+)/.exec(up))) { accPrint = accTravel = parseFloat(m[1]); }
          if ((m = /SQUARE_CORNER_VELOCITY=([\d.]+)/.exec(up))) machineCmd.scv = parseFloat(m[1]);
          if ((m = /\bVELOCITY=([\d.]+)/.exec(up))) machineCmd.vmax = parseFloat(m[1]);
        } else if (up.startsWith('PAUSE')) { addEvent({ move: n, kind: 'pause', label: 'Pause' }); pendingStop = true; }
        continue;
      }

      // ---- words
      for (const k in word) word[k] = NaN;
      let cmdLetter = '', cmdNum = NaN;
      const L = trimmed.length; let p = 0;
      while (p < L) {
        const ch = trimmed.charCodeAt(p);
        if (ch === 32 || ch === 9) { p++; continue; }
        const letter = String.fromCharCode(ch & ~32);
        p++;
        let q = p;
        while (q < L) { const d = trimmed.charCodeAt(q); if (d === 32 || d === 9) break; q++; }
        const v = parseFloat(trimmed.substring(p, q));
        if (!cmdLetter && (letter === 'G' || letter === 'M' || letter === 'T')) { cmdLetter = letter; cmdNum = v; }
        else if (letter in word) word[letter] = v;
        p = q;
      }

      if (cmdLetter === 'G') {
        const g = cmdNum;
        if (g === 0 || g === 1 || g === 2 || g === 3) {
          if (!isNaN(word.F) && word.F > 0) fmm = word.F / 60;
          let tx = x, ty = y, tz = z, te = e;
          if (!isNaN(word.X)) tx = absXYZ ? word.X : x + word.X;
          if (!isNaN(word.Y)) ty = absXYZ ? word.Y : y + word.Y;
          if (!isNaN(word.Z)) tz = absXYZ ? word.Z : z + word.Z;
          if (!isNaN(word.E)) te = absE ? word.E : e + word.E;
          const dE = te - e;
          if (!started && (!isNaN(word.X) || !isNaN(word.Y))) {
            // jump to the first commanded position instead of drawing a travel from 0,0
            started = true;
            P.a[n * 3] = tx + ox; P.a[n * 3 + 1] = ty + oy; P.a[n * 3 + 2] = tz + oz;
            x = tx; y = ty; z = tz; e = te;
            continue;
          }
          if (g === 2 || g === 3) {
            arcMove(g === 2, x, y, tx, ty, z, tz, dE, word.I, word.J, word.R, lineNo);
          } else {
            linearMove(tx + ox, ty + oy, tz + oz, dE, lineNo, false);
          }
          x = tx; y = ty; z = tz; e = te;
        } else if (g === 29 && isBambu && g29Window) {
          // bed leveling: no moves in the G-code; OrcaSlicer budgets 260 s for it on Bambu printers
          push(phys(0), phys(1), phys(2), FL_DWELL, 0, 0, 0, 260, lineNo);
          pendingStop = true;
        } else if (g === 4) {
          let s = 0;
          if (!isNaN(word.P)) s = word.P / 1000; else if (!isNaN(word.S)) s = word.S;
          if (s > 0) push(phys(0), phys(1), phys(2), FL_DWELL, 0, 0, 0, s, lineNo);
          pendingStop = true;
        } else if (g === 28) {
          // homing: the head goes somewhere we can't know; teleport, it is not printing anything
          if (isNaN(word.X) && isNaN(word.Y) && isNaN(word.Z)) { x = 0; y = 0; z = 0; }
          else { if (!isNaN(word.X)) x = 0; if (!isNaN(word.Y)) y = 0; if (!isNaN(word.Z)) z = 0; }
          ox = oy = oz = 0;
          pendingStop = true;
        } else if (g === 90) { absXYZ = true; absE = true; }
        else if (g === 91) { absXYZ = false; absE = false; }
        else if (g === 92) {
          if (!isNaN(word.E)) e = word.E;
          if (!isNaN(word.X)) { ox = phys(0) - word.X; x = word.X; }
          if (!isNaN(word.Y)) { oy = phys(1) - word.Y; y = word.Y; }
          if (!isNaN(word.Z)) { oz = phys(2) - word.Z; z = word.Z; }
          if (isNaN(word.E) && isNaN(word.X) && isNaN(word.Y) && isNaN(word.Z)) e = 0;
        }
      } else if (cmdLetter === 'M') {
        const mm = cmdNum;
        if (mm === 1002) {
          const m = /judge_flag\s+([A-Za-z0-9_]+)/.exec(trimmed);
          if (m) judge(m[1]);
          else if (/judge_last_extrude_cali_success/.test(trimmed)) judge('last_extrude_cali_success');
          continue;
        }
        if (mm === 622.1) { if (!isNaN(word.S)) nextDefault = word.S >= 0.5; continue; }
        if (mm === 622) {
          const want = !isNaN(word.J) ? word.J : !isNaN(word.S) ? word.S : 1;
          const runs = judged === (want >= 0.5);
          blockStack.push(runs && !skipping);
          if (want >= 0.5) g29Window = true;       // OrcaSlicer times G29 only inside "M622 J1" blocks
          updateSkipping();
          continue;
        }
        if (mm === 623) { blockStack.pop(); g29Window = false; updateSkipping(); continue; }
        if (mm === 82) absE = true;
        else if (mm === 83) absE = false;
        else if (mm === 204) {
          if (!isNaN(word.S)) { accPrint = word.S; accTravel = word.S; }
          if (!isNaN(word.P)) accPrint = word.P;
          if (!isNaN(word.T)) accTravel = word.T;
          if (!isNaN(word.R)) accRetract = word.R;
        } else if (mm === 201) {
          machineCmd.ax = isNaN(word.X) ? machineCmd.ax : word.X; machineCmd.ay = isNaN(word.Y) ? machineCmd.ay : word.Y;
          machineCmd.az = isNaN(word.Z) ? machineCmd.az : word.Z; machineCmd.ae = isNaN(word.E) ? machineCmd.ae : word.E;
        } else if (mm === 203) {
          machineCmd.vx = isNaN(word.X) ? machineCmd.vx : word.X; machineCmd.vy = isNaN(word.Y) ? machineCmd.vy : word.Y;
          machineCmd.vz = isNaN(word.Z) ? machineCmd.vz : word.Z; machineCmd.ve = isNaN(word.E) ? machineCmd.ve : word.E;
        } else if (mm === 205) {
          machineCmd.jx = isNaN(word.X) ? machineCmd.jx : word.X; machineCmd.jy = isNaN(word.Y) ? machineCmd.jy : word.Y;
          machineCmd.jz = isNaN(word.Z) ? machineCmd.jz : word.Z; machineCmd.je = isNaN(word.E) ? machineCmd.je : word.E;
          // M205 J is junction deviation on Marlin 2
          if (!isNaN(word.J)) machineCmd.jd = word.J;
        } else if (mm === 73) {
          if (!isNaN(word.P)) m73.push({ move: n, p: word.P });
        } else if (mm === 400) {
          // Bambu: "M400 S3" / "M400 P500" waits; plain M400 just drains the queue
          let s = 0; if (!isNaN(word.S)) s = word.S; else if (!isNaN(word.P)) s = word.P / 1000;
          if (s > 0) push(phys(0), phys(1), phys(2), FL_DWELL, 0, 0, 0, s, lineNo);
          pendingStop = true;
        } else if (mm === 109 || mm === 190 || mm === 191) {
          addEvent({ move: n, kind: 'heat', label: (mm === 190 ? 'Wait for bed ' : 'Wait for nozzle ') + (isNaN(word.S) ? '' : word.S + '°C') });
          pendingStop = true;
        } else if (mm === 600 || mm === 601 || mm === 0 || mm === 1 || mm === 25 || mm === 226) {
          addEvent({ move: n, kind: 'pause', label: mm === 600 ? 'Filament change (M600)' : 'Pause' });
          pendingStop = true;
        } else if (mm === 620 && !isNaN(word.S)) {
          // Bambu AMS: "M620 S1A" announces a filament change to slot 1
          const slot = word.S;
          if (slot < 255) addEvent({ move: n, kind: 'tool', label: 'Filament change → slot ' + (slot + 1), tool: slot });
          pendingStop = true;
        }
      } else if (cmdLetter === 'T') {
        if (!isNaN(cmdNum) && cmdNum < 255 && cmdNum >= 0) {
          if ((cmdNum | 0) !== curTool) {
            const prev = curTool; curTool = cmdNum | 0;
            const last = events[events.length - 1];
            // Bambu announces the change with M620 first; don't list the same change twice
            if (!(last && last.kind === 'tool' && last.move >= lastExtrudeMove)) addEvent({ move: n, kind: 'tool', label: 'Tool ' + prev + ' → ' + curTool, tool: curTool });
            else last.tool = curTool;
          }
          pendingStop = true;
        }
      }
    }

    function arcMove(cw, sx, sy, ex, ey, sz, ez, dE, I, J, R, lineNo) {
      let cx, cy;
      if (!isNaN(I) || !isNaN(J)) { cx = sx + (isNaN(I) ? 0 : I); cy = sy + (isNaN(J) ? 0 : J); }
      else if (!isNaN(R)) {
        const dx = ex - sx, dy = ey - sy, d = Math.hypot(dx, dy);
        if (d < 1e-9) { linearMove(ex + ox, ey + oy, ez + oz, dE, lineNo, false); return; }
        let h = Math.sqrt(Math.max(0, R * R - d * d / 4));
        if ((R < 0) !== !cw) h = -h;            // standard G-code R sign convention
        cx = sx + dx / 2 - h * dy / d; cy = sy + dy / 2 + h * dx / d;
      } else { linearMove(ex + ox, ey + oy, ez + oz, dE, lineNo, false); return; }
      const r = Math.hypot(sx - cx, sy - cy);
      let a0 = Math.atan2(sy - cy, sx - cx), a1 = Math.atan2(ey - cy, ex - cx);
      let sweep = a1 - a0;
      if (cw) { if (sweep >= -1e-9) sweep -= 2 * Math.PI; } else { if (sweep <= 1e-9) sweep += 2 * Math.PI; }
      const arcLen = Math.abs(sweep) * r;
      const segs = Math.max(1, Math.min(256, Math.ceil(Math.max(arcLen / 0.5, Math.abs(sweep) / (Math.PI / 24)))));
      for (let k = 1; k <= segs; k++) {
        const f = k / segs, a = a0 + sweep * f;
        const px = k === segs ? ex : cx + r * Math.cos(a);
        const py = k === segs ? ey : cy + r * Math.sin(a);
        linearMove(px + ox, py + oy, sz + (ez - sz) * f + oz, dE / segs, lineNo, true);
      }
    }

    if (progress) progress(1);
    if (!layers.length) layers.push({ z: 0, h: 0, first: 0 });

    while (blockStack.length) blockStack.pop();
    if (skipping) updateSkipping();
    const job = {
      moves: n, pts: P.out((n + 1) * 3),
      flags: G.flags.out(n), feat: G.feat.out(n), layer: G.layer.out(n), tool: G.tool.out(n),
      fcmd: G.fcmd.out(n), len: G.len.out(n), de: G.de.out(n), acc: G.acc.out(n), wait: G.wait.out(n),
      line: G.line.out(n), layers, events, m73, config, estimate, estimateSilent, lines: lineNo,
    };
    // drop empty layers produced by consecutive markers
    job.machine = resolveMachine(config, machineCmd);
    // moves were tagged with accel values known at parse time; 0 means "not set yet": fill defaults
    const m = job.machine;
    for (let k = 0; k < n; k++) {
      if (!(job.acc[k] > 0)) {
        const f = job.flags[k];
        job.acc[k] = (f & FL_EXTRUDE) ? m.accDefault : (f & FL_EONLY) ? m.accRetract : m.accTravel;
      }
    }
    job.flagsFound = Object.values(flagsFound);
    job.skippedMoves = skippedMoves;
    job.bed = resolveBed(job);
    return job;
  }

  /* ---------------------------------------------------------------- machine & bed */
  function resolveMachine(cfg, cmd) {
    const g = (k, d) => first(cfg[k], d);
    const flavor = String(cfg.gcode_flavor || '').toLowerCase();
    const m = {
      vx: cmd.vx || g('machine_max_speed_x', 500), vy: cmd.vy || g('machine_max_speed_y', 500),
      vz: cmd.vz || g('machine_max_speed_z', 20), ve: cmd.ve || g('machine_max_speed_e', 60),
      ax: cmd.ax || g('machine_max_acceleration_x', 20000), ay: cmd.ay || g('machine_max_acceleration_y', 20000),
      az: cmd.az || g('machine_max_acceleration_z', 500), ae: cmd.ae || g('machine_max_acceleration_e', 5000),
      jx: cmd.jx || g('machine_max_jerk_x', 9), jy: cmd.jy || g('machine_max_jerk_y', 9),
      jz: cmd.jz || g('machine_max_jerk_z', 3), je: cmd.je || g('machine_max_jerk_e', 2.5),
      accDefault: g('default_acceleration', 0) || g('machine_max_acceleration_extruding', 5000),
      accTravel: g('travel_acceleration', 0) || g('machine_max_acceleration_travel', 0) || g('default_acceleration', 0) || 5000,
      accRetract: g('machine_max_acceleration_retracting', 0) || 3000,
      flavor,
      jd: 0, mode: 'jerk',
      filamentDiameter: g('filament_diameter', 1.75),
      nozzle: g('nozzle_diameter', 0.4),
    };
    if (cmd.vmax) { m.vx = Math.min(m.vx, cmd.vmax); m.vy = Math.min(m.vy, cmd.vmax); }
    if (flavor === 'klipper' || cmd.scv) {
      const scv = cmd.scv || 5;
      m.mode = 'jd'; m.scv = scv;          // junction deviation is derived per-move from the accel
    } else if ((cmd.jd || g('machine_max_junction_deviation', 0)) > 0) {
      m.mode = 'jd'; m.jd = cmd.jd || g('machine_max_junction_deviation', 0.013);
    }
    return m;
  }

  function resolveBed(job) {
    const cfg = job.config;
    let poly = null;
    const area = cfg.printable_area || cfg.bed_shape;
    if (area) {
      const pts = String(area).replace(/[\[\]"']/g, '').split(',').map(s => s.trim().split('x').map(parseFloat))
        .filter(p => p.length === 2 && isFinite(p[0]) && isFinite(p[1]));
      if (pts.length >= 3) poly = pts;
    }
    // bounding box of extrusions as the fallback (and to frame the camera)
    let minX = 1e9, minY = 1e9, minZ = 1e9, maxX = -1e9, maxY = -1e9, maxZ = -1e9;
    const P = job.pts, F = job.flags;
    for (let k = 0; k < job.moves; k++) {
      if (!(F[k] & FL_EXTRUDE) || (F[k] & FL_SKIP)) continue;
      for (const q of [k, k + 1]) {
        const xx = P[q * 3], yy = P[q * 3 + 1], zz = P[q * 3 + 2];
        if (xx < minX) minX = xx; if (xx > maxX) maxX = xx;
        if (yy < minY) minY = yy; if (yy > maxY) maxY = yy;
        if (zz < minZ) minZ = zz; if (zz > maxZ) maxZ = zz;
      }
    }
    if (minX > maxX) { minX = minY = minZ = 0; maxX = maxY = 100; maxZ = 1; }
    if (!poly) {
      const pad = 10;
      poly = [[Math.floor(minX - pad), Math.floor(minY - pad)], [Math.ceil(maxX + pad), Math.floor(minY - pad)],
              [Math.ceil(maxX + pad), Math.ceil(maxY + pad)], [Math.floor(minX - pad), Math.ceil(maxY + pad)]];
    }
    let bx0 = 1e9, by0 = 1e9, bx1 = -1e9, by1 = -1e9;
    for (const p of poly) { bx0 = Math.min(bx0, p[0]); by0 = Math.min(by0, p[1]); bx1 = Math.max(bx1, p[0]); by1 = Math.max(by1, p[1]); }
    const structure = String(cfg.printer_structure || '').toLowerCase();
    return {
      poly, x0: bx0, y0: by0, x1: bx1, y1: by1, height: first(cfg.printable_height, Math.max(maxZ + 10, 100)),
      model: { minX, minY, minZ, maxX, maxY, maxZ },
      structure,
      bedSlinger: structure === 'i3',
    };
  }

  /* ---------------------------------------------------------------- planner */
  function planJob(job, opts) {
    opts = opts || {};
    const n = job.moves, P = job.pts, F = job.flags, m = job.machine;
    const vnom = new Float32Array(n), acc = new Float32Array(n);
    const ux = new Float32Array(n), uy = new Float32Array(n), uz = new Float32Array(n), ue = new Float32Array(n);
    const jl = new Float32Array(n);                 // max entry speed (junction limit)
    const safe = new Float32Array(n);               // speed allowed when starting/stopping from standstill
    const vi = new Float32Array(n), vf = new Float32Array(n), vp = new Float32Array(n);
    const dur = new Float32Array(n);
    const INF = 1e9;

    for (let k = 0; k < n; k++) {
      const L = job.len[k];
      if ((F[k] & FL_DWELL) || L <= 0) { vnom[k] = 0; continue; }
      let dx, dy, dz, de = job.de[k];
      if (F[k] & FL_EONLY) { dx = dy = dz = 0; }
      else { dx = P[k * 3 + 3] - P[k * 3]; dy = P[k * 3 + 4] - P[k * 3 + 1]; dz = P[k * 3 + 5] - P[k * 3 + 2]; }
      const inv = 1 / L;
      ux[k] = dx * inv; uy[k] = dy * inv; uz[k] = dz * inv; ue[k] = de * inv;
      let v = job.fcmd[k] > 0 ? job.fcmd[k] : 50;
      const lim = (vmax, u) => (Math.abs(u) > 1e-9 ? vmax / Math.abs(u) : INF);
      v = Math.min(v, lim(m.vx, ux[k]), lim(m.vy, uy[k]), lim(m.vz, uz[k]), lim(m.ve, ue[k]));
      let a = job.acc[k] > 0 ? job.acc[k] : 1000;
      a = Math.min(a, lim(m.ax, ux[k]), lim(m.ay, uy[k]), lim(m.az, uz[k]), lim(m.ae, ue[k]));
      vnom[k] = v; acc[k] = a;
      let s = v;
      s = Math.min(s, lim(m.jx, ux[k]), lim(m.jy, uy[k]), lim(m.jz, uz[k]), lim(m.je, ue[k]));
      safe[k] = Math.max(0, s);
    }

    // junction limits
    let prev = -1;
    for (let k = 0; k < n; k++) {
      if (vnom[k] <= 0) { prev = -1; continue; }
      if (prev < 0 || (F[k] & FL_STOP) || ((F[k] ^ F[prev]) & FL_EONLY)) { jl[k] = safe[k]; prev = k; continue; }
      const vmax = Math.min(vnom[prev], vnom[k]);
      let vj;
      if (m.mode === 'jd') {
        // junction deviation: v^2 = a * jd * sin(θ/2) / (1 - sin(θ/2)), θ the angle between directions
        const cos = -(ux[prev] * ux[k] + uy[prev] * uy[k] + uz[prev] * uz[k]);
        if (cos > 0.999999) vj = Math.min(safe[k], safe[prev]);       // full reversal
        else if (cos < -0.999999) vj = vmax;                           // straight
        else {
          const sinHalf = Math.sqrt(0.5 * (1 - cos));
          const a = Math.min(acc[prev], acc[k]);
          const jd = m.jd > 0 ? m.jd : (m.scv * m.scv * (Math.SQRT2 - 1)) / a;
          vj = Math.sqrt(a * jd * sinHalf / (1 - sinHalf));
        }
      } else {
        // classic jerk: the per-axis velocity step at the corner may not exceed the jerk limit
        vj = vmax;
        const chk = (d, j) => { const ad = Math.abs(d); if (ad > 1e-9) vj = Math.min(vj, j / ad); };
        chk(ux[prev] - ux[k], m.jx); chk(uy[prev] - uy[k], m.jy); chk(uz[prev] - uz[k], m.jz);
        chk(ue[prev] - ue[k], m.je);
        vj = Math.max(vj, Math.min(safe[prev], safe[k]));
      }
      jl[k] = Math.min(vj, vmax);
      prev = k;
    }

    // exit limit of a move: entry of the next moving move, or the standstill speed before a stop
    const exitMax = new Float32Array(n);
    for (let k = 0; k < n; k++) {
      if (vnom[k] <= 0) continue;
      const nx = k + 1;
      if (nx >= n || vnom[nx] <= 0 || (F[nx] & FL_STOP) || ((F[k] ^ F[nx]) & FL_EONLY)) exitMax[k] = safe[k];
      else exitMax[k] = INF;
    }
    // backward pass
    let nextEntry = 0;
    for (let k = n - 1; k >= 0; k--) {
      if (vnom[k] <= 0) { nextEntry = 0; continue; }
      const ex = exitMax[k] < INF ? exitMax[k] : nextEntry;
      vf[k] = ex;
      const e = Math.min(jl[k], Math.sqrt(ex * ex + 2 * acc[k] * job.len[k]));
      vi[k] = e;
      nextEntry = e;
    }
    // forward pass
    for (let k = 0; k < n; k++) {
      if (vnom[k] <= 0) continue;
      const reach = Math.sqrt(vi[k] * vi[k] + 2 * acc[k] * job.len[k]);
      if (vf[k] > reach) vf[k] = reach;
      if (k + 1 < n && vnom[k + 1] > 0 && exitMax[k] >= INF) {
        if (vi[k + 1] > vf[k]) vi[k + 1] = vf[k];
        else vf[k] = vi[k + 1];
      }
    }
    // trapezoids
    let t = 0; const t0 = new Float64Array(n);
    for (let k = 0; k < n; k++) {
      t0[k] = t;
      if (F[k] & FL_DWELL) { dur[k] = job.wait[k]; t += dur[k]; continue; }
      const L = job.len[k];
      if (vnom[k] <= 0 || L <= 0) { dur[k] = 0; continue; }
      const a = acc[k], v0 = Math.min(vi[k], vnom[k]), v1 = Math.min(vf[k], vnom[k]);
      vi[k] = v0; vf[k] = v1;
      let vpk = vnom[k];
      let da = (vpk * vpk - v0 * v0) / (2 * a), dd = (vpk * vpk - v1 * v1) / (2 * a);
      if (da + dd > L) {
        vpk = Math.sqrt(Math.max(0, (2 * a * L + v0 * v0 + v1 * v1) / 2));
        vpk = Math.max(vpk, v0, v1);
        da = Math.max(0, (vpk * vpk - v0 * v0) / (2 * a)); dd = Math.max(0, L - da);
      }
      vp[k] = vpk;
      const ta = (vpk - v0) / a, td = (vpk - v1) / a;
      const tc = Math.max(0, L - da - dd) / vpk;
      dur[k] = Math.max(1e-6, ta + tc + td);
      t += dur[k];
    }
    job.vi = vi; job.vf = vf; job.vp = vp; job.ac = acc; job.vnom = vnom;
    job.plannerT0 = t0; job.plannerDur = dur; job.plannerTotal = t;
    applyTiming(job, opts.align !== false);
    return job;
  }

  /* Map planner time onto the slicer's estimate using its M73 progress markers, piecewise linearly.
     The slicer simulates the firmware more faithfully than any viewer can, so when it left markers
     we trust its clock and only use our planner for what happens *between* the markers. */
  function applyTiming(job, align) {
    const n = job.moves, t0p = job.plannerT0, dp = job.plannerDur, F = job.flags;
    /* Only motion is stretched to fit the estimate. Fixed waits (G4, M400 S/P, the G29 budget) last
       exactly what they say in both clocks, so they are taken out of both sides before mapping. */
    const fixedBefore = new Float64Array(n + 1);          // fixed-wait time before move k (planner clock)
    for (let k = 0; k < n; k++) fixedBefore[k + 1] = fixedBefore[k] + ((F[k] & FL_DWELL) ? dp[k] : 0);
    const fixedTotal = fixedBefore[n];
    const motionAt = (k) => (k < n ? t0p[k] : job.plannerTotal) - fixedBefore[Math.min(k, n)];
    const motionTotal = job.plannerTotal - fixedTotal, targetMotion = job.estimate - fixedTotal;
    const knotsA = [0], knotsB = [0];
    let usable = align && job.estimate > 0 && job.m73.length >= 3 && motionTotal > 0 && targetMotion > 0;
    if (usable) {
      let lastP = -1;
      for (const mk of job.m73) {
        if (mk.p <= lastP || mk.p <= 0 || mk.p >= 100) continue;
        const ta = motionAt(mk.move);
        const tb = job.estimate * mk.p / 100 - fixedBefore[Math.min(mk.move, n)];
        if (ta <= knotsA[knotsA.length - 1] + 1e-6 || tb <= knotsB[knotsB.length - 1] + 1e-6) continue;
        knotsA.push(ta); knotsB.push(tb); lastP = mk.p;
      }
      knotsA.push(motionTotal); knotsB.push(Math.max(targetMotion, knotsB[knotsB.length - 1] + 1e-3));
      // sanity: wildly different totals mean the markers belong to some other clock (e.g. silent mode)
      const ratio = targetMotion / motionTotal;
      if (knotsA.length < 4 || ratio < 0.3 || ratio > 3) usable = false;
    }
    const t0 = new Float64Array(n), dur = new Float32Array(n);
    if (!usable) {
      t0.set(t0p); dur.set(dp);
      job.total = job.plannerTotal; job.aligned = false;
    } else {
      let seg = 0;
      const map = (ta) => {
        while (seg < knotsA.length - 2 && ta > knotsA[seg + 1]) seg++;
        const a0 = knotsA[seg], a1 = knotsA[seg + 1], b0 = knotsB[seg], b1 = knotsB[seg + 1];
        return b0 + (b1 - b0) * (a1 > a0 ? (ta - a0) / (a1 - a0) : 0);
      };
      let t = 0;
      for (let k = 0; k < n; k++) {
        t0[k] = t;
        if (F[k] & FL_DWELL) { dur[k] = dp[k]; }
        else { const a = motionAt(k); dur[k] = Math.max(0, map(a + dp[k]) - map(a)); }
        t += dur[k];
      }
      job.total = t; job.aligned = true;
    }
    // blocks the printer won't run still count toward the slicer's estimate (it times every line),
    // so they are aligned like everything else and only then taken out of the clock
    if (job.skippedMoves) {
      let t = 0;
      for (let k = 0; k < n; k++) {
        if (job.flags[k] & FL_SKIP) dur[k] = 0;
        t0[k] = t; t += dur[k];
      }
      job.total = t;
    }
    job.t0 = t0; job.dur = dur;
    // layer timing
    for (let L = 0; L < job.layers.length; L++) {
      const a = job.layers[L].first, b = L + 1 < job.layers.length ? job.layers[L + 1].first : n;
      job.layers[L].t0 = a < n ? t0[a] : job.total;
      job.layers[L].t1 = b < n ? t0[b] : job.total;
    }
  }

  /* index of the move active at time t (binary search on t0) */
  function moveAt(job, t) {
    const T = job.t0; let lo = 0, hi = job.moves - 1;
    if (hi < 0) return 0;
    if (t <= T[0]) return 0;
    if (t >= T[hi]) return hi;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (T[mid] <= t) lo = mid; else hi = mid - 1; }
    return lo;
  }

  /* position along move k (0..L) and instantaneous speed, given time t inside it */
  function stateIn(job, k, t) {
    const L = job.len[k];
    const D = job.dur[k], Dp = job.plannerDur[k];
    if (!(D > 0) || !(Dp > 0) || !(L > 0) || (job.flags[k] & FL_DWELL)) return { frac: t >= job.t0[k] + D ? 1 : 0, v: 0 };
    let tau = (t - job.t0[k]) / D * Dp;                // planner-time inside the move
    if (tau < 0) tau = 0; if (tau > Dp) tau = Dp;
    const a = job.ac[k], v0 = job.vi[k], v1 = job.vf[k], vpk = job.vp[k];
    const ta = (vpk - v0) / a, td = (vpk - v1) / a, tc = Math.max(0, Dp - ta - td);
    let s, v;
    if (tau < ta) { s = v0 * tau + 0.5 * a * tau * tau; v = v0 + a * tau; }
    else if (tau < ta + tc) { const da = v0 * ta + 0.5 * a * ta * ta; s = da + vpk * (tau - ta); v = vpk; }
    else {
      const da = v0 * ta + 0.5 * a * ta * ta, dc = vpk * tc, u = tau - ta - tc;
      s = da + dc + vpk * u - 0.5 * a * u * u; v = vpk - a * u;
    }
    return { frac: Math.max(0, Math.min(1, s / L)), v: Math.max(0, v) };
  }

  const api = { parseGcode, planJob, applyTiming, moveAt, stateIn, FEATURES, featureId, parseDuration,
                FL_EXTRUDE, FL_TRAVEL, FL_EONLY, FL_DWELL, FL_ARC, FL_STOP, FL_SKIP, FLAG_INFO, flagLabel };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PlaybackCore = api;
})(typeof self !== 'undefined' ? self : this);
