import time
from playwright.sync_api import sync_playwright
html=open('../dist/playback.html').read()
with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-webgl","--ignore-gpu-blocklist"]); errs=[]
    pg=b.new_page(viewport={'width':1300,'height':820}); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.set_content(html); pg.wait_for_timeout(300)
    pg.evaluate("t=>PlaybackApp.loadText(t,{name:'bambu.gcode'})", open('bambu.gcode').read()); pg.wait_for_timeout(500)
    pg.evaluate("()=>PlaybackApp.seek(100)"); pg.wait_for_timeout(200)
    pg.click('#codeToggle'); pg.wait_for_timeout(600)
    cur = lambda: pg.evaluate("()=>{const c=document.querySelector('#codeRows .ln.cur'); return c? +c.dataset.line : null}")
    print('open: current row shown =', cur(), '| HUD line =', pg.evaluate("()=>PlaybackApp.job.line[PlaybackCore.moveAt(PlaybackApp.job, PlaybackApp.time)]"))
    pg.screenshot(path='shots/g1_panel.png')
    pg.evaluate("()=>{PlaybackApp.setPlaying(true)}"); pg.wait_for_timeout(1500); pg.evaluate("()=>PlaybackApp.setPlaying(false)"); pg.wait_for_timeout(500)
    print('follows while playing: current row visible =', cur())
    pg.mouse.move(150, 500); pg.mouse.wheel(0, 900); pg.wait_for_timeout(300)
    print('after wheel: follow button =', pg.inner_text('#codeFollow'), '| cur visible =', cur())
    # click a row far away -> seek
    row = pg.query_selector('#codeRows .ln:nth-child(5)'); no = int(row.get_attribute('data-line'))
    t0 = pg.evaluate("()=>PlaybackApp.time"); row.click(); pg.wait_for_timeout(300)
    t1 = pg.evaluate("()=>PlaybackApp.time"); hudline = pg.evaluate("()=>PlaybackApp.job.line[PlaybackCore.moveAt(PlaybackApp.job, PlaybackApp.time)]")
    print('clicked line', no, '-> time', round(t0,2), '->', round(t1,2), '| now running line', hudline, '| text:', pg.inner_text('#hSrc')[:60])
    pg.click('#codeFollow'); pg.wait_for_timeout(600); print('follow again: cur visible =', cur())
    pg.screenshot(path='shots/g2_after.png')
    # big file
    pg.evaluate("t=>PlaybackApp.loadText(t,{name:'big.gcode'})", open('big.gcode').read()); pg.wait_for_timeout(1000)
    pg.evaluate("()=>PlaybackApp.seek(PlaybackApp.job.total*0.97)"); pg.wait_for_timeout(1500)
    print('big file (1M lines): info =', pg.inner_text('#codeInfo'), '| cur visible =', cur(), '| rows in DOM =', pg.evaluate("()=>document.querySelectorAll('#codeRows .ln').length"))
    b.close(); print(errs or 'no errors')
