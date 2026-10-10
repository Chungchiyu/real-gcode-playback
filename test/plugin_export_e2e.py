# End to end through the real plugin, the way OrcaSlicer runs it: the page is get_ui() loaded as a
# string (like WebView2's NavigateToString, so no secure context), it must be under WebView2's 2 MB,
# it fetches the video encoders from the plugin, encodes an MP4 and a WebM, and the plugin writes
# them into its exports folder. ffprobe checks the files.
import sys, os, json, shutil, time, queue, importlib.util, tempfile, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mock'))
import orca
from playwright.sync_api import sync_playwright
work = tempfile.mkdtemp(prefix='orca_data_'); pdir = os.path.join(work, 'orca_plugins', 'playback'); os.makedirs(pdir)
shutil.copy('../dist/orca_playback.py', pdir)
spec = importlib.util.spec_from_file_location('orca_playback', os.path.join(pdir, 'orca_playback.py'))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
orca._pkg().register_capabilities(); PageCls, _ = orca._registered; page_cap = PageCls()
outq = queue.Queue(); orca.pages.PagesPluginCapabilityBase.sender = outq.put
bad = []; errs = []
def check(name, ok, info=''):
    print(('ok  ' if ok else 'FAIL') + ' ' + name, info)
    if not ok: bad.append(name)
html = page_cap.get_ui()
size = len(html.encode('utf-8'))
check('page fits WebView2 NavigateToString (2 MB)', size < 2 * 1024 * 1024, f'{size} bytes')
BRIDGE = """<script>(function () { var handlers = [];
  window.orca = { postMessage: function (d) { window.__toPy(JSON.stringify(d === undefined ? null : d)); },
                  onMessage: function (cb) { if (typeof cb === 'function') handlers.push(cb); } };
  window.__orcaDispatch = function (p) { var d = p ? p.data : null; for (var i = 0; i < handlers.length; i++) { try { handlers[i](d); } catch (e) { console.error(e); } } };
})();</script>"""
def pump(pg, until, timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        moved = False
        while True:
            try: m = outq.get_nowait()
            except queue.Empty: break
            pg.evaluate("m => window.__orcaDispatch({data: JSON.parse(m)})", m); moved = True
        if pg.evaluate(until): return True
        if not moved: time.sleep(0.03)
    return False
g = open('bambu.gcode').read()
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={'width': 1000, 'height': 640})
    pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
    pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
    pg.expose_function('__toPy', lambda s: page_cap.on_message(json.loads(s)))
    pg.set_content(html.replace('<head>', '<head>' + BRIDGE, 1)); pg.wait_for_timeout(500)
    pump(pg, "()=>true", 2)
    check('start screen shows', pg.is_visible('#empty .box'))
    check('encoders are not part of the page', pg.evaluate("()=>typeof HME") == 'undefined')
    pg.evaluate("t => PlaybackApp.loadText(t,{name:'Cylinder.gcode',when:'test'})", g); pg.wait_for_timeout(800)
    for fmt, codec in [('mp4', 'h264'), ('webm', 'vp8')]:
        pg.click('#expBtn'); pg.wait_for_timeout(300)
        pg.select_option('#xFmt', fmt); pg.select_option('#xRange', 'time'); pg.fill('#xT0', '1:00'); pg.fill('#xT1', '1:20')
        pg.select_option('#xSpeed', '10'); pg.select_option('#xSize', '480'); pg.select_option('#xFps', '15')
        frames = pg.evaluate("()=>PlaybackApp._exportPlan().frames")
        pg.evaluate("()=>{PlaybackApp._export.last=null}")
        pg.click('#xGo')
        done = pump(pg, "()=>!!(PlaybackApp._export.last && !PlaybackApp._export.running)")
        last = pg.evaluate("()=>PlaybackApp._export.last")
        check(fmt + ': exported through the plugin', done and last and not last['isErr'], last)
        path = os.path.join(pdir, 'exports', 'Cylinder.' + fmt)
        if os.path.exists(path):
            info = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                                              'stream=codec_name,height,nb_read_frames', '-of', 'json', path], capture_output=True, text=True).stdout)
            st = info['streams'][0]
            check(fmt + ': ' + codec + ', the planned ' + str(frames) + ' frames, 480p', st['codec_name'] == codec and int(st['nb_read_frames']) == frames and st['height'] == 480, st)
        else:
            check(fmt + ': file in the exports folder', False, os.listdir(os.path.join(pdir, 'exports')) if os.path.isdir(os.path.join(pdir, 'exports')) else 'no exports folder')
        if pg.is_visible('#expDlg .box'): pg.click('#xClose')
    b.close()
shutil.rmtree(work)
print('\n'.join(errs) or 'no page errors')
if bad or errs: raise SystemExit('FAIL plugin_export_e2e: ' + ', '.join(bad))
