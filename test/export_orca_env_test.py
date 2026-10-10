# Export inside OrcaSlicer's page: not a secure context (WebView2 NavigateToString), so no WebCodecs
# and no Save dialog. MP4 (H.264, minih264) and WebM (VP8, libvpx) are encoded frame by frame by the
# bundled WebAssembly encoders, and must match the plan exactly: frame count, length and size.
# The file is handed to the plugin, and the dialog shows where it was saved. ffprobe checks the files.
import base64, json, os, subprocess, tempfile
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
bad = []; errs = []
def check(name, ok, info=''):
    print(('ok  ' if ok else 'FAIL') + ' ' + name, info)
    if not ok: bad.append(name)
def probe(data, suffix):
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f: f.write(data); path = f.name
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                        'stream=codec_name,width,height,nb_read_frames,avg_frame_rate:format=duration', '-of', 'json', path],
                       capture_output=True, text=True)
    info = json.loads(r.stdout or '{}'); s = (info.get('streams') or [{}])[0]
    # a frame from the middle: is there a picture in it?
    mid = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-vf', 'select=eq(n\\,%d),scale=64:32' % (int(s.get('nb_read_frames', 2)) // 2),
                          '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], capture_output=True).stdout
    os.unlink(path)
    return {'codec': s.get('codec_name'), 'w': s.get('width'), 'h': s.get('height'), 'frames': int(s.get('nb_read_frames') or 0),
            'fps': s.get('avg_frame_rate'), 'contrast': (max(mid) - min(mid)) if mid else 0}
def file_bytes(pg, idx):
    parts = pg.evaluate("i=>Object.values(window.__files)[i].parts", idx)
    return b''.join(base64.b64decode(x) for x in parts)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={'width': 1000, 'height': 640})
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.set_content(html.replace('<head>', '<head><script>' + INIT + '</script>', 1)); pg.wait_for_timeout(300)
    print('secure context:', pg.evaluate("()=>isSecureContext"), '| VideoEncoder:', pg.evaluate("()=>typeof VideoEncoder"))
    pg.evaluate("t => PlaybackApp.loadText(t,{name:'Cylinder.gcode',when:'test'})", g); pg.wait_for_timeout(800)
    pg.click('#expBtn'); pg.wait_for_timeout(400)
    codecs = pg.evaluate("()=>PlaybackApp._export.codecs")
    check('MP4 and WebM offered without WebCodecs', codecs.get('mp4', {}).get('via') == 'h264' and codecs.get('webm', {}).get('via') == 'vpx', codecs)
    n = 0
    for fmt, fps, speed, size in [('mp4', '30', '10', '480'), ('webm', '24', '5', '720')]:
        if n: pg.click('#expBtn'); pg.wait_for_timeout(300)
        pg.select_option('#xFmt', fmt); pg.select_option('#xRange', 'time'); pg.fill('#xT0', '1:00'); pg.fill('#xT1', '1:30')
        pg.select_option('#xSpeed', speed); pg.select_option('#xSize', size); pg.select_option('#xFps', fps); pg.wait_for_timeout(300)
        plan = pg.evaluate("()=>PlaybackApp._exportPlan()")
        summ = pg.inner_text('#xSum')
        check(fmt + ': summary shows the file size', 'File size: up to about' in summ, summ.replace('\n', ' | '))
        pg.click('#xGo')
        pg.wait_for_function("n=>Object.keys(window.__files).length>n && PlaybackApp._export.last && !PlaybackApp._export.running", arg=n, timeout=240000)
        last = pg.evaluate("()=>PlaybackApp._export.last")
        check(fmt + ': saved through the plugin', not last['isErr'] and 'exports' in last['msg'], last)
        m = probe(file_bytes(pg, n), '.' + fmt)
        want = {'mp4': 'h264', 'webm': 'vp8'}[fmt]
        check(fmt + ': codec ' + want, m['codec'] == want, m)
        check(fmt + ': exactly the planned frames, size and rate', m['frames'] == plan['frames'] and m['w'] == plan['size']['w'] and m['h'] == plan['size']['h']
              and abs(eval(m['fps']) - int(fps)) / int(fps) < 0.03, (m, plan['frames'], plan['size']))   # WebM times are whole ms
        check(fmt + ': frames show the print', m['contrast'] > 40, m['contrast'])
        n += 1
    check('dialog shows where it was saved', pg.is_visible('#xResultPath') and 'exports' in pg.inner_text('#xResultPath'))
    pg.screenshot(path='shots/export_saved_path.png')
    b.close()
print('\n'.join(errs) or 'no page errors')
if bad or errs: raise SystemExit('FAIL export_orca_env_test: ' + ', '.join(bad))
