from playwright.sync_api import sync_playwright
html=open('../dist/playback.html').read()
with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-webgl","--ignore-gpu-blocklist"]); errs=[]
    pg=b.new_page(viewport={'width':1300,'height':820}); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.set_content(html); pg.wait_for_timeout(300)
    pg.evaluate("t=>PlaybackApp.loadText(t,{name:'b'})", open('bambu.gcode').read()); pg.wait_for_timeout(400)
    pg.click('#codeToggle'); pg.wait_for_timeout(500)
    pg.evaluate("()=>{document.getElementById('speedSel').value='25';document.getElementById('speedSel').dispatchEvent(new Event('change'));PlaybackApp.seek(60);PlaybackApp.setPlaying(true)}")
    pos=[]
    for i in range(12):
        pg.wait_for_timeout(150)
        pos.append(pg.evaluate("""()=>{const c=document.querySelector('#codeRows .ln.cur'); if(!c) return null;
           const s=document.getElementById('codeScroll').getBoundingClientRect(), r=c.getBoundingClientRect(); return Math.round(r.top-s.top)}"""))
    print('cur row offset from panel top while playing 250x:', pos, '| panel height', pg.evaluate("()=>document.getElementById('codeScroll').clientHeight"))
    pg.evaluate("()=>PlaybackApp.setPlaying(false)"); pg.wait_for_timeout(200)
    pg.screenshot(path='shots/g3_center.png', clip={'x':0,'y':40,'width':500,'height':600}); b.close(); print(errs or 'no errors')
