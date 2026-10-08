# Screenshots of the actual cross-section: scarf seam from the side, Z-contoured top lines, uniform for comparison.
import sys
from playwright.sync_api import sync_playwright
html = open('../dist/playback.html').read()
g = open('bead.gcode').read()
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={'width': 1200, 'height': 760})
    pg.on('console', lambda m: errs.append(m.type + ': ' + m.text) if m.type in ('error', 'warning') else None)
    pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
    pg.set_content(html); pg.wait_for_timeout(400)
    pg.evaluate("t => PlaybackApp.loadText(t,{name:'bead.gcode',when:'test'})", g)
    pg.wait_for_timeout(1200)
    pg.evaluate("()=>{PlaybackApp.setPrefs({head:false,gantry:false}); PlaybackApp.seek(PlaybackApp.job.total)}"); pg.wait_for_timeout(300)
    # scarf seam on layer 2 along y=80, x 80..100: look from the front (-y), slightly above
    pg.evaluate("()=>PlaybackApp.look(90,80,0.3, 90,72,1.2)"); pg.wait_for_timeout(300)
    pg.screenshot(path='shots/bead_scarf_side.png')
    pg.evaluate("()=>{PlaybackApp.setPrefs({color:'beadh'})}"); pg.select_option('#colorSel', 'beadh'); pg.wait_for_timeout(300)
    pg.screenshot(path='shots/bead_scarf_height.png')
    # Z-contoured lines on layer 3: y 85..86.5, x 85..115, from the side
    pg.evaluate("()=>PlaybackApp.look(100,86,0.5, 100,74,2.5)"); pg.wait_for_timeout(300)
    pg.screenshot(path='shots/bead_zaa_height.png')
    pg.evaluate("()=>{PlaybackApp.setPrefs({color:'feature'})}"); pg.select_option('#colorSel', 'feature')
    pg.evaluate("()=>PlaybackApp.look(90,80,0.3, 90,72,1.2)")
    pg.evaluate("()=>PlaybackApp.setPrefs({lines:'uniform'})"); pg.wait_for_timeout(400)
    pg.screenshot(path='shots/bead_scarf_uniform.png')
    pg.evaluate("()=>PlaybackApp.setPrefs({lines:'fat'})"); pg.wait_for_timeout(300)
    hud = pg.evaluate("()=>{PlaybackApp.seek(PlaybackApp.job.t0[30]+0.01); return document.getElementById('hBead').textContent}")
    print('HUD line at move 30:', hud)
    b.close()
print('\n'.join(errs) or 'no console errors')
