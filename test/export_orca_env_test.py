# Export inside OrcaSlicer's page: not a secure context (WebView2 NavigateToString), so no WebCodecs
# and no Save dialog. Video goes through MediaRecorder, paced frame by frame; the file is handed
# to the plugin, and the dialog shows where it was saved.
import base64
from playwright.sync_api import sync_playwright
html = open('../dist/playback.html').read(); g = open('bambu.gcode').read()
INIT = """
window.__files = {}; window.__orcaHandlers = [];
window.orca = { postMessage: (m) => {
    if (m.cmd === 'save_begin') window.__files[m.id] = { name: m.name, size: m.size, parts: [] };
    if (m.cmd === 'save_chunk') window.__files[m.id].parts.push(m.data);
    if (m.cmd === 'save_end') setTimeout(() => window.__orcaHandlers.forEach(h => h({ cmd: 'saved', id: m.id, ok: true,
        path: 'C:\\\\Users\\\\nick\\\\AppData\\\\Roaming\\\\OrcaSlicer\\\\orca_plugins\\\\real\\\\exports\\\\' + window.__files[m.id].name })), 10); },
  onMessage: (cb) => window.__orcaHandlers.push(cb) };
"""
DECODE = """async (id) => { const f = window.__files[id]; const bin = atob(f.parts.join('')); /* parts are separate base64 strings */
  return null; }"""
bad = []; errs = []
def check(name, ok, info=''):
    print(('ok  ' if ok else 'FAIL') + ' ' + name, info)
    if not ok: bad.append(name)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={'width': 1000, 'height': 640})
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.set_content(html.replace('<head>', '<head><script>' + INIT + '</script>', 1)); pg.wait_for_timeout(300)
    print('secure context:', pg.evaluate("()=>isSecureContext"), '| VideoEncoder:', pg.evaluate("()=>typeof VideoEncoder"))
    pg.evaluate("t => PlaybackApp.loadText(t,{name:'Cylinder.gcode',when:'test'})", g); pg.wait_for_timeout(800)
    pg.click('#expBtn'); pg.wait_for_timeout(400)
    opts = pg.evaluate("()=>[...document.getElementById('xFmt').options].map(o=>o.value+(o.disabled?'(off)':''))")
    check('video formats offered without WebCodecs', 'webm' in opts and 'gif' in opts, opts)
    codecs = pg.evaluate("()=>PlaybackApp._export.codecs")
    print('   codecs:', codecs)
    pg.select_option('#xFmt', 'webm'); pg.select_option('#xRange', 'time'); pg.fill('#xT0', '1:00'); pg.fill('#xT1', '1:30')
    pg.select_option('#xSpeed', '10'); pg.select_option('#xSize', '480'); pg.select_option('#xFps', '15')
    pg.wait_for_timeout(400)
    summ = pg.inner_text('#xSum')
    check('summary has a file size and the real-time note', 'File size: up to about' in summ and 'real time' in summ, summ.replace('\n', ' | '))
    pg.click('#xGo')
    pg.wait_for_function("()=>PlaybackApp._export.last", timeout=120000)
    last = pg.evaluate("()=>PlaybackApp._export.last")
    check('saved through the plugin', not last['isErr'] and 'exports' in last['msg'], last)
    check('dialog stays open and shows the path', pg.is_visible('#xResultPath') and 'exports' in pg.inner_text('#xResultPath'), pg.inner_text('#xResult').replace('\n', ' | '))
    pg.screenshot(path='shots/export_saved_path.png')
    m = pg.evaluate("""async () => { const f = Object.values(window.__files)[0]; const bytes = [];
      for (const part of f.parts) { const bin = atob(part); for (let k = 0; k < bin.length; k++) bytes.push(bin.charCodeAt(k)); }
      const u = new Uint8Array(bytes); const v = document.createElement('video'); v.muted = true;
      v.src = URL.createObjectURL(new Blob([u], { type: 'video/webm' }));
      await new Promise((res, rej) => { v.onloadedmetadata = res; v.onerror = () => rej(new Error('decode')); });
      if (!isFinite(v.duration)) { v.currentTime = 1e9; await new Promise((r) => { v.ontimeupdate = r; }); }
      const d = v.duration; v.currentTime = d / 2; await new Promise((r) => { v.onseeked = r; });
      const c = document.createElement('canvas'); c.width = 64; c.height = 32; const g = c.getContext('2d'); g.drawImage(v, 0, 0, 64, 32);
      const px = g.getImageData(0, 0, 64, 32).data; let lo = 255, hi = 0; for (let i = 0; i < px.length; i += 4) { const l = px[i] + px[i + 1] + px[i + 2]; lo = Math.min(lo, l); hi = Math.max(hi, l); }
      return { w: v.videoWidth, h: v.videoHeight, d, size: u.length, name: f.name, contrast: hi - lo }; }""")
    check('recorded WebM decodes: about 3 s at 480p', abs(m['d'] - 3) < 0.35 and m['h'] == 480, m)
    check('frames show the print, not a blank picture', m['contrast'] > 60, m['contrast'])
    # MP4 through the recorder too
    pg.click('#xClose'); pg.click('#expBtn'); pg.wait_for_timeout(300)
    pg.select_option('#xFmt', 'mp4'); pg.click('#xGo')
    pg.wait_for_function("()=>Object.keys(window.__files).length>1 && PlaybackApp._export.last && !PlaybackApp._export.running", timeout=120000)
    last = pg.evaluate("()=>PlaybackApp._export.last")
    check('MP4 recorded and saved', not last['isErr'] and last['msg'].split(' (')[0].endswith('.mp4'), last)
    b.close()
print('\n'.join(errs) or 'no page errors')
if bad or errs: raise SystemExit('FAIL export_orca_env_test: ' + ', '.join(bad))
