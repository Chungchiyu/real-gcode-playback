# Camera: rotation pivots on the point under the cursor without jumping, the wheel zooms toward the
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
    # screen position of a world point
    proj = "p=>PlaybackApp._project(p)"
    # a point on the print: an outer-wall vertex near the middle of the file (bed coordinates)
    pt = pg.evaluate("()=>{const j=PlaybackApp.job;const k=Math.floor(j.moves*0.6);for(let i=k;i<j.moves;i++){if(j.flags[i]&1)return [j.pts[i*3],j.pts[i*3+1],j.pts[i*3+2]-j.beadH[i]/2]}}")
    sx, sy = pg.evaluate(proj, pt)
    pt = pg.evaluate("a=>PlaybackApp._pick(a[0],a[1])", [sx, sy])     # the nearest line under the cursor
    check('cursor over the print picks a line', pt is not None, pt)
    sx, sy = pg.evaluate(proj, pt)
    c0 = pg.evaluate(cam)
    pg.mouse.move(sx, sy); pg.mouse.down()
    pg.mouse.move(sx + 1, sy); c1 = pg.evaluate(cam)
    p0 = pg.evaluate(proj, c1['pivot'])
    check('pivot is under the cursor', abs(p0[0] - sx) < 5 and abs(p0[1] - sy) < 5, (round(p0[0] - sx, 1), round(p0[1] - sy, 1)))
    check('no jump when a drag starts', abs(c1['dir'][0]-c0['dir'][0]) + abs(c1['dir'][1]-c0['dir'][1]) + abs(c1['dir'][2]-c0['dir'][2]) < 0.05, c1['dir'])
    for i in range(10): pg.mouse.move(sx + 1 + i * 12, sy + i * 5)
    mk = pg.evaluate("()=>PlaybackApp._marker()")
    check('pivot marker shows while turning', mk['visible'] and mk['opacity'] > 0.9, mk)
    pg.mouse.up(); pg.wait_for_timeout(100)
    c2 = pg.evaluate(cam); nx, ny = pg.evaluate(proj, c2['pivot'])
    check('rotated', abs(c2['dir'][0]-c0['dir'][0]) + abs(c2['dir'][1]-c0['dir'][1]) > 0.2)
    check('the pivot stays put on screen while rotating', abs(nx - p0[0]) < 1 and abs(ny - p0[1]) < 1, (round(nx - p0[0], 2), round(ny - p0[1], 2)))
    # empty space: pivot is the print centre, not the stale target
    ex, ey = next((x, y) for x, y in [(900, 140), (1000, 600), (450, 650), (300, 150)] if pg.evaluate("a=>PlaybackApp._pick(a[0],a[1])", [x, y]) is None)
    pg.mouse.move(ex, ey); pg.mouse.down(); pg.mouse.move(ex + 100, ey); pg.mouse.up()
    m = pg.evaluate("()=>PlaybackApp.job.bed.model"); pv = pg.evaluate(cam)['pivot']
    check('rotating over empty space turns about the print', abs(pv[0] - (m['minX'] + m['maxX']) / 2) < 0.5 and abs(pv[1] - (m['minY'] + m['maxY']) / 2) < 0.5, pv)
    pg.wait_for_timeout(700)
    mk = pg.evaluate("()=>PlaybackApp._marker()")
    check('pivot marker fades out after release', not mk['visible'], mk)
    # wheel toward the cursor: the point under it stays put
    sx, sy = pg.evaluate(proj, pt)
    d0 = pg.evaluate(cam)['dist']
    pg.mouse.move(sx, sy)
    for i in range(5): pg.mouse.wheel(0, -120); pg.wait_for_timeout(30)
    nx, ny = pg.evaluate(proj, pt); d1 = pg.evaluate(cam)['dist']
    check('wheel zooms in', d1 < d0 * 0.8, (round(d0), round(d1)))
    check('wheel zooms toward the cursor', abs(nx - sx) < 4 and abs(ny - sy) < 4, (round(nx - sx, 1), round(ny - sy, 1)))
    # zoomed right up to a line, the line under the cursor is too close to turn about: use the print's centre
    near_pt = None
    for i in range(30):
        pg.mouse.wheel(0, -120); pg.wait_for_timeout(20)
        near_pt = pg.evaluate("a=>PlaybackApp._pick(a[0],a[1])", [sx, sy])
        d = pg.evaluate("p=>{const c=PlaybackApp._cam().posBed;const m=PlaybackApp.job.bed.model;const q=[(m.minX+m.maxX)/2,(m.minY+m.maxY)/2,(m.minZ+m.maxZ)/2];"
                        "return [Math.hypot(c[0]-p[0],c[1]-p[1],c[2]-p[2]), Math.hypot(c[0]-q[0],c[1]-q[1],c[2]-q[2])]}", near_pt) if near_pt else None
        if d and d[0] < 0.25 * d[1]: break
    print('   near-lens setup: camera to point / to centre', d)
    pg.mouse.down(); pg.mouse.move(sx + 30, sy); pv = pg.evaluate(cam)['pivot']; pg.mouse.up()
    dcam = pg.evaluate("()=>PlaybackApp._cam()")
    check('a pick right in front of the lens falls back to the print centre', near_pt is not None and abs(pv[0] - (m['minX'] + m['maxX']) / 2) < 0.5, (near_pt, pv))
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
