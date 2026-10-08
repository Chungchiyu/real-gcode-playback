from playwright.sync_api import sync_playwright
html=open('../dist/playback.html').read()
with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-webgl","--ignore-gpu-blocklist"]); errs=[]
    pg=b.new_page(viewport={'width':1300,'height':860}); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.set_content(html); pg.wait_for_timeout(300)
    pg.evaluate("t=>PlaybackApp.loadText(t,{name:'bambu_flags.gcode'})", open('bambu_flags.gcode').read()); pg.wait_for_timeout(600)
    pg.evaluate("()=>PlaybackApp.seek(PlaybackApp.job.total*0.5)"); pg.wait_for_timeout(200)
    st=lambda: pg.evaluate("()=>({total: Math.round(PlaybackApp.job.total), frac: +(PlaybackApp.time/PlaybackApp.job.total).toFixed(3), badge: document.getElementById('timingBadge').textContent})")
    print('before:', st())
    pg.click('#optBtn'); pg.wait_for_timeout(200)
    print('options:', pg.evaluate("()=>[...document.querySelectorAll('#flagList label')].map(l=>(l.querySelector('input').checked?'[x] ':'[ ] ')+l.textContent.trim())"))
    pg.click('input[data-flag="timelapse_record_flag"]'); pg.wait_for_timeout(1500)
    print('timelapse on:', st(), '| toast:', pg.inner_text('#toast'))
    pg.click('input[data-flag="g29_before_print_flag"]'); pg.wait_for_timeout(1500)
    print('leveling off:', st(), '| toast:', pg.inner_text('#toast'))
    pg.screenshot(path='shots/f1_flags.png'); b.close(); print(errs or 'no errors')
