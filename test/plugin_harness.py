import sys, os, json, shutil, time, queue, importlib.util, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mock'))
import orca
from playwright.sync_api import sync_playwright
work = tempfile.mkdtemp(prefix='orca_data_')
pdir = os.path.join(work, 'orca_plugins', 'playback'); os.makedirs(pdir)
shutil.copy('../dist/orca_playback.py', pdir)
spec = importlib.util.spec_from_file_location('orca_playback', os.path.join(pdir, 'orca_playback.py'))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
orca._pkg().register_capabilities()
PageCls, CapCls = orca._registered
page_cap, capture = PageCls(), CapCls()
print('capabilities:', page_cap.get_name(), '/', capture.get_name(), '| icon', page_cap.get_icon())
outq = queue.Queue()
orca.pages.PagesPluginCapabilityBase.sender = outq.put
BRIDGE = r"""
(function () {
  var handlers = [];
  window.orca = { postMessage: function (d) { window.__toPy(JSON.stringify({channel:'orca',kind:'message',data:d===undefined?null:d})); },
                  onMessage: function (cb) { if (typeof cb === 'function') handlers.push(cb); } };
  window.__orcaDispatch = function (p) { var d = p ? p.data : null; for (var i = 0; i < handlers.length; i++) { try { handlers[i](d); } catch (e) { console.error(e); } } };
})();"""
errs, sent = [], []
def pump(pg, ms=300):
    end = time.time() + ms / 1000
    while time.time() < end:
        try:
            m = outq.get(timeout=0.05)
            sent.append(json.loads(m).get('cmd'))
            pg.evaluate("m => window.__orcaDispatch({data: JSON.parse(m)})", m)
        except queue.Empty:
            pass
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={'width': 1400, 'height': 860})
    pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
    recv=[]
    def _toPy(s):
        d=json.loads(s)['data']; recv.append(d.get('cmd')); page_cap.on_message(d)
    pg.expose_function('__toPy', _toPy)
    pg.add_init_script(BRIDGE)
    html = page_cap.get_ui()
    print('page html', len(html), 'chars')
    pg.route('http://orca.local/', lambda r: r.fulfill(body=html, content_type='text/html'))
    pg.goto('http://orca.local/'); pump(pg, 800)
    print('after hello, py sent:', sent)
    pg.screenshot(path='shots/p0_setup.png')
    # 1) slice happens: the capture step runs on the exported file
    gpath = os.path.join(work, 'tmpgcode'); os.makedirs(gpath); shutil.copy('bambu.gcode', os.path.join(gpath, 'plate_1.gcode'))
    ctx = types.SimpleNamespace(step=orca.Step.psGCodePostProcess, gcode_path=os.path.join(gpath, 'plate_1.gcode'), host='File', output_name='Cylinder_PLA_4m43s.gcode')
    r = capture.execute(ctx); print('capture:', r.status, r.message, os.listdir(os.path.join(pdir, '.captures')))
    assert open(ctx.gcode_path).read() == open('bambu.gcode').read(), 'capture modified the G-code!'
    page_cap.on_lifecycle_event(orca.LifecycleEvent.SlicingJobComplete, types.SimpleNamespace(code=orca.LifecycleEvtCode.Ok))
    pump(pg, 5000)
    info = pg.evaluate("()=>{const j=PlaybackApp.job; return j ? {moves:j.moves,total:j.total,aligned:j.aligned,name:document.getElementById('fileName').textContent, info:document.getElementById('fileInfo').textContent} : null}")
    print('loaded via plugin:', info); print('messages:', sent[:4], '...', len(sent), 'total')
    pg.evaluate("()=>PlaybackApp.seek(PlaybackApp.job.total*0.7)"); pump(pg, 300)
    pg.screenshot(path='shots/p1_loaded.png')
    # 2) prefs round trip
    pg.select_option('#colorSel', 'flow'); pump(pg, 900)
    print('saved prefs:', orca._Base._configs, 'page sent cmds via bridge:', pg.evaluate('()=>1'))
    # 3) temp fallback with no capture: fake OrcaSlicer temp layout for this pid
    shutil.rmtree(os.path.join(pdir, '.captures'))
    tmp = tempfile.gettempdir(); pid = os.getpid()
    root = os.path.join(tmp, f'orcaslicer_{os.getuid()}', 'orcaslicer_model', 'Thu_Oct_08', f'22_47_11#{pid}#1', 'Metadata'); os.makedirs(root, exist_ok=True)
    shutil.copy('marlin.gcode', os.path.join(root, f'.{pid}.0.gcode'))
    page_cap.slice_done_at = time.time()
    pg.click('#btnLatest'); pump(pg, 4000)
    info = pg.evaluate("()=>{const j=PlaybackApp.job; return {moves:j.moves,bedSlinger:j.bed.bedSlinger,info:document.getElementById('fileInfo').textContent}}")
    print('loaded via temp fallback:', info)
    shutil.rmtree(os.path.join(tmp, f'orcaslicer_{os.getuid()}'))
    b.close()
print('page->py cmds:', recv)
print('\n'.join(errs) or 'no page errors')
