# The plugin side of exporting: a file sent in base64 parts lands in the plugin's exports folder,
# names are cleaned up, existing files are not overwritten, other file types are refused.
import sys, os, json, base64, shutil, tempfile, queue, importlib.util
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mock'))
import orca
work = tempfile.mkdtemp(prefix='orca_data_'); pdir = os.path.join(work, 'orca_plugins', 'playback'); os.makedirs(pdir)
shutil.copy('../dist/orca_playback.py', pdir)
spec = importlib.util.spec_from_file_location('orca_playback', os.path.join(pdir, 'orca_playback.py'))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
orca._pkg().register_capabilities(); PageCls, _ = orca._registered; page = PageCls()
out = queue.Queue(); orca.pages.PagesPluginCapabilityBase.sender = out.put
bad = []
def check(name, ok, info=''):
    print(('ok  ' if ok else 'FAIL') + ' ' + name, info)
    if not ok: bad.append(name)
def send_file(sid, name, data, chunk=1000):
    parts = [data[i:i + chunk] for i in range(0, len(data), chunk)] or [b'']
    page.on_message({'cmd': 'save_begin', 'id': sid, 'name': name, 'size': len(data), 'chunks': len(parts)})
    for i, p in enumerate(parts): page.on_message({'cmd': 'save_chunk', 'id': sid, 'i': i, 'data': base64.b64encode(p).decode()})
    page.on_message({'cmd': 'save_end', 'id': sid})
    msgs = []
    while not out.empty(): msgs.append(json.loads(out.get()))
    return [m for m in msgs if m.get('cmd') == 'saved']
data = os.urandom(5000)
r = send_file('a', 'My print.mp4', data)
path = r[-1].get('path') if r else None
check('saved into the plugin exports folder', r and r[-1]['ok'] and path and os.path.dirname(path) == os.path.join(pdir, 'exports'), r)
check('content is intact', path and open(path, 'rb').read() == data)
r2 = send_file('b', 'My print.mp4', b'second')
check('an existing file is not overwritten', r2[-1]['ok'] and r2[-1]['path'].endswith('My print (2).mp4'), r2[-1].get('path'))
r3 = send_file('c', '../../evil.mp4', b'x')
check('no way out of the folder', r3[-1]['ok'] and os.path.dirname(r3[-1]['path']) == os.path.join(pdir, 'exports'), r3[-1].get('path'))
r4 = send_file('d', 'script.py', b'print(1)')
check('other file types are refused', not r4[-1]['ok'] and not os.path.exists(os.path.join(pdir, 'exports', 'script.py')), r4[-1])
shutil.rmtree(work)
if bad: raise SystemExit('FAIL plugin_export_test: ' + ', '.join(bad))
