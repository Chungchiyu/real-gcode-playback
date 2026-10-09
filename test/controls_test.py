# Camera: OrcaSlicer-style turntable about the middle of the screen (no jump), the wheel zooms toward the
# cursor, zoom works even when a drag never saw its pointerup, a reload keeps the view and the time.
from playwright.sync_api import sync_playwright
html = open('../dist/playback.html').read()
g = open('bambu.gcode').read(); g2 = open('bead.gcode').read()
errs = []; bad = []
def check(name, ok, info=''):
    print(('ok  ' if ok else 'FAIL') + ' ' + name, info)
    if not ok: bad.append(name)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={'width': 1200, 'height': 760})
    pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
    pg.set_content(html); pg.wait_for_timeout(300)
    pg.evaluate("t => PlaybackApp.loadText(t,{name:'a.gcode',when:'test'})", g); pg.wait_for_timeout(800)
    pg.evaluate("()=>{PlaybackApp.setPrefs({head:false,gantry:false}); PlaybackApp.seek(PlaybackApp.job.total)}"); pg.wait_for_timeout(200)
    cam = "()=>PlaybackApp._cam()"
    proj = "p=>PlaybackApp._project(p)"
    box = pg.evaluate("()=>{const r=document.getElementById('gl').getBoundingClientRect();return [r.left+r.width/2, r.top+r.height/2]}")
    cx, cy = box
    # aim at a wall of the printed cylinder (world = bed + the moving bed's offset)
    pg.evaluate("""()=>{const j=PlaybackApp.job, c=PlaybackApp._cam(); const oy=c.pos[1]-c.posBed[1];
      let k=Math.floor(j.moves*0.5); while(!(j.flags[k]&1)) k++;
      const x=j.pts[k*3], y=j.pts[k*3+1]+oy, z=j.pts[k*3+2]; PlaybackApp.look(x,y,z, x-90,y-110,z+90)}""")
    centre_hit = pg.evaluate("a=>PlaybackApp._pick(a[0],a[1])", [cx, cy])
    check('a line is straight ahead', centre_hit is not None, centre_hit)
    c0 = pg.evaluate(cam)
    sx, sy = 300, 600                                    # drag starts far from the middle of the screen
    pg.mouse.move(sx, sy); pg.mouse.down()
    pg.mouse.move(sx + 1, sy); c1 = pg.evaluate(cam)
    check('no jump when a drag starts', sum(abs(a - b) for a, b in zip(c1['dir'], c0['dir'])) < 0.05, c1['dir'])
    p0 = pg.evaluate(proj, c1['pivot'])
    check('pivot is the middle of the screen', abs(p0[0] - cx) < 1.5 and abs(p0[1] - cy) < 1.5, (round(p0[0] - cx, 2), round(p0[1] - cy, 2)))
    check('pivot is the line straight ahead', sum(abs(a - b) for a, b in zip(c1['pivot'], centre_hit)) < 0.5, c1['pivot'])
    for i in range(10): pg.mouse.move(sx + 1 + i * 12, sy - i * 5)
    pg.mouse.up(); pg.wait_for_timeout(100)
    c2 = pg.evaluate(cam); nx, ny = pg.evaluate(proj, c2['pivot'])
    check('rotated', sum(abs(a - b) for a, b in zip(c2['dir'], c0['dir'])) > 0.2)
    check('the pivot stays in the middle while rotating', abs(nx - cx) < 1.5 and abs(ny - cy) < 1.5, (round(nx - cx, 2), round(ny - cy, 2)))
    # nothing straight ahead: turn about the current view centre (still the middle of the screen)
    pg.evaluate("()=>PlaybackApp.look(150,150,0, 150,40,90)")       # looking at an empty part of the bed
    empty = pg.evaluate("a=>PlaybackApp._pick(a[0],a[1])", [cx, cy])
    pg.mouse.move(sx, sy); pg.mouse.down(); pg.mouse.move(sx + 80, sy); c3 = pg.evaluate(cam); pg.mouse.up()
    q = pg.evaluate(proj, c3['pivot'])
    check('nothing straight ahead: still turns about the middle of the screen', empty is None and abs(q[0] - cx) < 1.5 and abs(q[1] - cy) < 1.5, (empty, round(q[0] - cx, 2), round(q[1] - cy, 2)))
    pg.evaluate("""()=>{const j=PlaybackApp.job, c=PlaybackApp._cam(); const oy=c.pos[1]-c.posBed[1];
      let k=Math.floor(j.moves*0.5); while(!(j.flags[k]&1)) k++;
      const x=j.pts[k*3], y=j.pts[k*3+1]+oy, z=j.pts[k*3+2]; PlaybackApp.look(x,y,z, x-90,y-110,z+90)}""")
    pt = pg.evaluate("a=>PlaybackApp._pick(a[0],a[1])", [cx, cy])
    # wheel toward the cursor: the point under it stays put
    sx, sy = pg.evaluate(proj, pt)
    d0 = pg.evaluate(cam)['dist']
    pg.mouse.move(sx, sy)
    for i in range(5): pg.mouse.wheel(0, -120); pg.wait_for_timeout(30)
    nx, ny = pg.evaluate(proj, pt); d1 = pg.evaluate(cam)['dist']
    check('wheel zooms in', d1 < d0 * 0.8, (round(d0), round(d1)))
    check('wheel zooms toward the cursor', abs(nx - sx) < 4 and abs(ny - sy) < 4, (round(nx - sx, 1), round(ny - sy, 1)))
    pg.evaluate("()=>PlaybackApp.look(90,90,5, -60,-80,140)")
    # a drag whose release was never seen: OrbitControls ignored the wheel from then on
    pg.mouse.move(600, 400); pg.mouse.down(); pg.mouse.move(620, 410)
    pg.evaluate("()=>window.dispatchEvent(new Event('blur'))")       # e.g. released over another window
    d2 = pg.evaluate(cam)['dist']; pg.mouse.wheel(0, 240); pg.wait_for_timeout(50); d3 = pg.evaluate(cam)['dist']
    check('wheel still zooms after a lost release', d3 > d2 * 1.1, (round(d2), round(d3)))
    pg.mouse.up()
    # zoom while a drag is still in progress also works
    pg.mouse.move(600, 400); pg.mouse.down(); d4 = pg.evaluate(cam)['dist']; pg.mouse.wheel(0, 240); pg.wait_for_timeout(50)
    d5 = pg.evaluate(cam)['dist']; pg.mouse.up()
    check('wheel works during a drag', abs(d5 - d4) > 1, (round(d4), round(d5)))
    # reload: keep the view and the time
    pg.evaluate("()=>PlaybackApp.seek(100)")
    before = pg.evaluate(cam)
    pg.evaluate("t => PlaybackApp.loadText(t,{name:'a2.gcode',when:'test'})", g); pg.wait_for_timeout(800)
    after = pg.evaluate(cam); t = pg.evaluate("()=>PlaybackApp.time")
    check('re-slice keeps the camera', sum(abs(a - b) for a, b in zip(before['pos'], after['pos'])) < 1e-3, after['pos'])
    check('re-slice keeps the time', abs(t - 100) < 1e-6, t)
    pg.evaluate("t => PlaybackApp.loadText(t,{name:'short.gcode',when:'test'})", g2); pg.wait_for_timeout(800)
    t2 = pg.evaluate("()=>PlaybackApp.time"); tot = pg.evaluate("()=>PlaybackApp.job.total")
    check('time past the new end starts over', t2 == 0, (t2, round(tot, 1)))
    b.close()
print('\n'.join(errs) or 'no page errors')
if bad or errs: raise SystemExit('FAIL controls_test: ' + ', '.join(bad))
