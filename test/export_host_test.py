# Inside OrcaSlicer without a Save dialog (macOS/Linux): the page hands the file to the plugin in
# base64 parts and reports where it was saved.
import os, base64, json
from playwright.sync_api import sync_playwright
url = 'file://' + os.path.abspath('../dist/playback.html')
g = open('bambu.gcode').read()
INIT = """
delete window.showSaveFilePicker;
window.__got = []; window.__orcaHandlers = [];
window.orca = { postMessage: (m) => { window.__got.push(m);
    if (m.cmd === 'save_end') setTimeout(() => window.__orcaHandlers.forEach(h => h({ cmd: 'saved', id: m.id, ok: true, path: 'C:/data/orca_plugins/x/exports/a.png' })), 10); },
  onMessage: (cb) => window.__orcaHandlers.push(cb) };
"""
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={'width': 900, 'height': 600}); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.add_init_script(INIT); pg.goto(url); pg.wait_for_timeout(300)
    pg.evaluate("t => PlaybackApp.loadText(t,{name:'Cyl.gcode',when:'test'})", g); pg.wait_for_timeout(800)
    pg.click('#expBtn'); pg.wait_for_timeout(200); pg.click('#xTabImage'); pg.click('#xGo')
    pg.wait_for_function("()=>PlaybackApp._export.last", timeout=60000)
    last = pg.evaluate("()=>PlaybackApp._export.last")
    msgs = pg.evaluate("()=>window.__got.filter(m=>m.cmd&&m.cmd.startsWith('save_'))")
    begin = [m for m in msgs if m['cmd'] == 'save_begin'][0]
    data = b''.join(base64.b64decode(m['data']) for m in msgs if m['cmd'] == 'save_chunk')
    ok = (last['msg'].startswith('Saved to C:/data') and data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) == begin['size'])
    print(('ok  ' if ok else 'FAIL') + ' image handed to the plugin and its saved path shown', last, begin['name'], len(data))
    b.close()
print('\n'.join(errs) or 'no page errors')
if not ok or errs: raise SystemExit('FAIL export_host_test')
