# Export: the dialog's ranges and summary, MP4/WebM/GIF videos that decode with the right length and
# size, images of the 3D view and of the whole window. The system Save dialog is replaced by a stub
# that keeps what was written.
import os, base64, struct
from playwright.sync_api import sync_playwright
url = 'file://' + os.path.abspath('../dist/playback.html')
g = open('bambu.gcode').read()
errs = []; bad = []
def check(name, ok, info=''):
    print(('ok  ' if ok else 'FAIL') + ' ' + name, info)
    if not ok: bad.append(name)
STUB = """() => { window.__saved = []; window.showSaveFilePicker = async (o) => ({ name: o.suggestedName, createWritable: async () => {
  const parts = []; return { write: async (b) => parts.push(b), close: async () => {
    const blob = new Blob(parts); const buf = new Uint8Array(await blob.arrayBuffer()); let s = '';
    for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    window.__saved.push({ name: o.suggestedName, size: buf.length, b64: btoa(s) }); } }; } }); }"""
PROBE = """async (i) => { const f = window.__saved[i]; const bin = atob(f.b64); const u = new Uint8Array(bin.length); for (let k = 0; k < u.length; k++) u[k] = bin.charCodeAt(k);
  const type = f.name.endsWith('.mp4') ? 'video/mp4' : 'video/webm'; const v = document.createElement('video'); v.muted = true;
  v.src = URL.createObjectURL(new Blob([u], { type }));
  await new Promise((res, rej) => { v.onloadedmetadata = res; v.onerror = () => rej(new Error('decode error ' + (v.error && v.error.code))); });
  if (!isFinite(v.duration)) { v.currentTime = 1e9; await new Promise((r) => { v.ontimeupdate = r; }); }
  return { w: v.videoWidth, h: v.videoHeight, d: v.duration }; }"""
def run_export(pg):
    n = pg.evaluate("()=>window.__saved.length")
    pg.click('#xGo')
    pg.wait_for_function("n=>window.__saved.length>n || (PlaybackApp._export.last && PlaybackApp._export.last.isErr)", arg=n, timeout=240000)
    last = pg.evaluate("()=>PlaybackApp._export.last")
    return pg.evaluate("n=>window.__saved[n] ? {name: window.__saved[n].name, size: window.__saved[n].size} : null", n), last
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={'width': 1100, 'height': 700})
    pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
    pg.goto(url); pg.wait_for_timeout(300); pg.evaluate(STUB)
    pg.evaluate("t => PlaybackApp.loadText(t,{name:'Cylinder.gcode',when:'test'})", g); pg.wait_for_timeout(800)
    pg.evaluate("()=>PlaybackApp.seek(120)")
    check('Export button enabled once a print is loaded', not pg.is_disabled('#expBtn'))
    pg.click('#expBtn'); pg.wait_for_timeout(300)
    check('dialog opens', pg.is_visible('#expDlg .box'))
    pg.screenshot(path='shots/export_dialog.png')
    tot = pg.evaluate("()=>PlaybackApp.job.total")
    plan = pg.evaluate("()=>PlaybackApp._exportPlan()")
    check('whole print by default, fitted into 30 s', abs(plan['t1'] - tot) < 1e-6 and plan['t0'] == 0 and abs(plan['length'] - 30) < 1e-6, (round(plan['length'], 2), plan['frames']))
    pg.select_option('#xRange', 'layer'); plan = pg.evaluate("()=>PlaybackApp._exportPlan()")
    L = pg.evaluate("()=>{const j=PlaybackApp.job;const L=j.layers[j.layer[Math.max(0,j.t0.findIndex(t=>t>120)-1)]];return [L.t0,L.t1]}")
    check('current layer range', abs(plan['t0'] - L[0]) < 1e-6 and abs(plan['t1'] - L[1]) < 1e-6, (plan['t0'], plan['t1'], L))
    pg.select_option('#xRange', 'layers'); pg.fill('#xL0', '3'); pg.fill('#xL1', '5'); plan = pg.evaluate("()=>PlaybackApp._exportPlan()")
    check('layers 3–5', plan.get('t1', 0) > plan.get('t0', 0), (plan.get('t0'), plan.get('t1')))
    check('layer rows shown only for that mode', pg.is_visible('#xLayersRow') and not pg.is_visible('#xTimeRow'))
    pg.select_option('#xRange', 'events'); nopt = pg.evaluate("()=>document.getElementById('xEv0').options.length")
    check('event list: start, events, end', nopt >= 3, nopt)
    pg.select_option('#xRange', 'time'); pg.fill('#xT0', '1:00'); pg.fill('#xT1', '1:30'); plan = pg.evaluate("()=>PlaybackApp._exportPlan()")
    check('custom time 1:00–1:30', plan['t0'] == 60 and plan['t1'] == 90, (plan['t0'], plan['t1']))
    pg.fill('#xT1', 'abc'); summ = pg.inner_text('#xSum')
    check('bad time is flagged and Export disabled', 'Times look like' in summ and pg.is_disabled('#xGo'), summ)
    pg.fill('#xT1', '1:30')
    # WebM: 30 s of print at 10x, 480p, 15 fps -> 3 s, 45 frames
    pg.select_option('#xFmt', 'webm'); pg.select_option('#xSpeed', '10'); pg.select_option('#xSize', '480'); pg.select_option('#xFps', '15')
    plan = pg.evaluate("()=>PlaybackApp._exportPlan()")
    check('plan: 45 frames, 3 s', plan['frames'] == 45 and abs(plan['length'] - 3) < 1e-6, plan['frames'])
    f, last = run_export(pg)
    check('WebM saved', f is not None and f['name'].endswith('.webm') and f['size'] > 1000, (f, last))
    if f:
        m = pg.evaluate(PROBE, 0)
        check('WebM decodes: 3 s, 480p', abs(m['d'] - 3) < 0.15 and m['h'] == 480, m)
    check('time is put back after export', abs(pg.evaluate("()=>PlaybackApp.time") - 120) < 1e-6)
    check('dialog closes after a successful export', not pg.is_visible('#expDlg .box'))
    # MP4 (H.264 when the system has it, else VP9 in MP4)
    pg.click('#expBtn'); pg.wait_for_timeout(200)
    pg.select_option('#xFmt', 'mp4'); codec = pg.evaluate("()=>PlaybackApp._export.codecs.mp4")
    f, last = run_export(pg)
    check('MP4 saved (' + str(codec) + ')', f is not None and f['name'].endswith('.mp4'), (f, last))
    if f:
        # this test browser has no H.264 decoder: check the file with ffprobe
        import subprocess, json, tempfile
        raw = base64.b64decode(pg.evaluate("()=>window.__saved[1].b64"))
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tf: tf.write(raw); path = tf.name
        info = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                                          'stream=codec_name,height,nb_read_frames:format=duration', '-of', 'json', path], capture_output=True, text=True).stdout)
        os.unlink(path); st = info['streams'][0]
        check('MP4 decodes: 45 frames (3 s), 480p', int(st['nb_read_frames']) == 45 and st['height'] == 480 and st['codec_name'] in ('h264', 'vp9'), st)
    # GIF
    pg.click('#expBtn'); pg.wait_for_timeout(200)
    pg.select_option('#xFmt', 'gif'); pg.select_option('#xSpeed', '25')
    f, last = run_export(pg)
    check('GIF saved', f is not None and f['name'].endswith('.gif'), (f, last))
    if f:
        raw = base64.b64decode(pg.evaluate("()=>window.__saved[2].b64"))
        w, h = struct.unpack('<HH', raw[6:10])
        frames = raw.count(b'\x21\xf9\x04')
        check('GIF header, size and frames', raw[:6] == b'GIF89a' and h == 480 and frames >= 15, (w, h, frames))
    # stop part-way
    pg.click('#expBtn'); pg.wait_for_timeout(200)
    pg.select_option('#xRange', 'all'); pg.select_option('#xFmt', 'webm'); pg.select_option('#xSpeed', 'fit60'); pg.select_option('#xFps', '30')
    n0 = pg.evaluate("()=>window.__saved.length")
    pg.click('#xGo'); pg.wait_for_timeout(1500); pg.click('#xCancel')
    pg.wait_for_function("()=>!PlaybackApp._export.running", timeout=60000)
    check('Stop cancels without saving', pg.evaluate("()=>window.__saved.length") == n0 and 'stopped' in pg.evaluate("()=>PlaybackApp._export.last.msg"))
    pg.keyboard.press('Escape'); pg.wait_for_timeout(100)
    # images
    pg.click('#expBtn'); pg.wait_for_timeout(200); pg.click('#xTabImage')
    pg.select_option('#xImgFmt', 'png'); f, last = run_export(pg)
    raw = base64.b64decode(pg.evaluate("n=>window.__saved[n].b64", pg.evaluate("()=>window.__saved.length-1")))
    w, h = struct.unpack('>II', raw[16:24])
    check('PNG of the 3D view', raw[:8] == b'\x89PNG\r\n\x1a\n' and w > 500, (w, h))
    open('shots/export_render.png', 'wb').write(raw)
    pg.click('#expBtn'); pg.wait_for_timeout(200); pg.click('#xTabImage')
    pg.check('input[name=xWhat][value=window]'); pg.select_option('#xImgFmt', 'jpeg'); f, last = run_export(pg)
    raw = base64.b64decode(pg.evaluate("n=>window.__saved[n].b64", pg.evaluate("()=>window.__saved.length-1")))
    check('JPEG of the whole window', raw[:3] == b'\xff\xd8\xff' and f['name'].endswith('.jpg'), (f, last))
    open('shots/export_window.jpg', 'wb').write(raw)
    b.close()
print('\n'.join(errs) or 'no page errors')
if bad or errs: raise SystemExit('FAIL export_test: ' + ', '.join(bad))
