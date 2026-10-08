import sys, os, json, shutil, time, queue, importlib.util, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mock'))
import orca
from playwright.sync_api import sync_playwright
work = tempfile.mkdtemp(prefix='orca_data_'); pdir = os.path.join(work, 'orca_plugins', 'playback'); os.makedirs(pdir)
shutil.copy('../dist/orca_playback.py', pdir)
spec = importlib.util.spec_from_file_location('orca_playback', os.path.join(pdir, 'orca_playback.py'))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
orca._pkg().register_capabilities(); PageCls, CapCls = orca._registered
page_cap, capture = PageCls(), CapCls()
outq = queue.Queue(); orca.pages.PagesPluginCapabilityBase.sender = outq.put
BRIDGE = r"""(function(){var h=[];window.orca={postMessage:function(d){window.__toPy(JSON.stringify({data:d===undefined?null:d}))},onMessage:function(cb){h.push(cb)}};
window.__orcaDispatch=function(p){var d=p?p.data:null;for(var i=0;i<h.length;i++){try{h[i](d)}catch(e){console.error(e)}}};
window.__hidden=false;Object.defineProperty(document,'hidden',{get:function(){return window.__hidden}});})();"""
errs=[]; recv=[]
def pump(pg, ms=300):
    end=time.time()+ms/1000
    while time.time()<end:
        try: m=outq.get(timeout=0.05); pg.evaluate("m=>window.__orcaDispatch({data:JSON.parse(m)})", m)
        except queue.Empty: pass
gdir=os.path.join(work,'tmp'); os.makedirs(gdir)
def slice_(src, name):
    shutil.copy(src, os.path.join(gdir,'p.gcode')); time.sleep(0.05)
    capture.execute(types.SimpleNamespace(step=orca.Step.psGCodePostProcess, gcode_path=os.path.join(gdir,'p.gcode'), host='File', output_name=name))
    page_cap.on_lifecycle_event(orca.LifecycleEvent.SlicingJobComplete, types.SimpleNamespace(code=orca.LifecycleEvtCode.Ok))
def vis(pg, hidden):
    pg.evaluate("h=>{window.__hidden=h;document.dispatchEvent(new Event('visibilitychange'))}", hidden)
state = "()=>({job: PlaybackApp.job ? PlaybackApp.job.moves : null, name: document.getElementById('fileName').textContent, prompt: !document.getElementById('newSlice').hidden})"
with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-webgl","--ignore-gpu-blocklist"])
    pg=b.new_page(viewport={'width':1300,'height':800})
    pg.on('console', lambda m: errs.append(m.text) if m.type=='error' else None); pg.on('pageerror', lambda e: errs.append(str(e)))
    def toPy(s):
        d=json.loads(s)['data']; recv.append(d.get('cmd')); page_cap.on_message(d)
    pg.expose_function('__toPy', toPy); pg.add_init_script(BRIDGE)
    html=page_cap.get_ui(); pg.route('http://orca.local/', lambda r: r.fulfill(body=html, content_type='text/html'))
    pg.goto('http://orca.local/'); pump(pg, 800)
    print('1 first visit, nothing sliced:', pg.evaluate(state))
    vis(pg, True); slice_('bambu.gcode','Cylinder_A'); pump(pg, 4000)
    print('2 sliced while away (still hidden):', pg.evaluate(state))
    vis(pg, False); pump(pg, 4000)
    print('3 back on tab, nothing loaded before -> auto load:', pg.evaluate(state))
    pg.evaluate("()=>{PlaybackApp.seek(30); PlaybackApp.setPlaying(true)}"); pump(pg, 400)
    vis(pg, True); pump(pg, 200)
    print('4 leaving tab pauses: playing =', pg.evaluate("()=>document.querySelector('#playIco rect')!==null"))
    slice_('marlin.gcode','Cylinder_B'); pump(pg, 4000); vis(pg, False); pump(pg, 1500)
    print('5 new slice, already loaded -> asks:', pg.evaluate(state))
    pg.screenshot(path='shots/n1_prompt.png')
    pg.click('#nsKeep'); pump(pg, 300); print('6 keep current:', pg.evaluate(state))
    vis(pg, True); pump(pg, 200); vis(pg, False); pump(pg, 1500)
    print('7 same slice not asked again:', pg.evaluate(state))
    slice_('marlin.gcode','Cylinder_C'); pump(pg, 4000); vis(pg, True); pump(pg,200); vis(pg, False); pump(pg, 1500)
    print('8 newer slice -> asks again:', pg.evaluate(state))
    pg.click('#nsLoad'); pump(pg, 5000); print('9 load it:', pg.evaluate(state))
    pg.evaluate("()=>PlaybackApp.seek(PlaybackApp.job.total*0.6)"); pump(pg, 300)
    pg.screenshot(path='shots/n2_tube.png')
    for sh in ['layers','height','flat']:
        pg.click('#optBtn'); pg.select_option('#shadeSel', sh); pg.click('#optBtn'); pump(pg, 300); pg.screenshot(path=f'shots/n3_{sh}.png')
    pg.click('#optBtn'); pg.uncheck('#gantryChk'); pg.click('#optBtn'); pump(pg,300); pg.screenshot(path='shots/n4_nogantry.png')
    b.close()
print('page->py:', recv); print('\n'.join(errs) or 'no page errors')
