from playwright.sync_api import sync_playwright
html=open('../dist/playback.html').read()
with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-webgl","--ignore-gpu-blocklist"]); errs=[]
    pg=b.new_page(viewport={'width':1200,'height':800}); pg.on('pageerror', lambda e: errs.append(str(e)))
    sent=[]; pg.expose_function('__toPy', lambda s: sent.append(s))
    pg.add_init_script("window.orca={postMessage:d=>window.__toPy(JSON.stringify(d)),onMessage:()=>{}}; window.__focus=true; document.hasFocus=()=>window.__focus;")
    pg.route('http://x.local/', lambda r: r.fulfill(body=html, content_type='text/html')); pg.goto('http://x.local/'); pg.wait_for_timeout(300)
    pg.evaluate("t=>PlaybackApp.loadText(t,{name:'b'})", open('bambu.gcode').read()); pg.wait_for_timeout(400)
    playing=lambda: pg.evaluate("()=>document.querySelector('#playIco rect')!==null")
    leave="()=>{window.__focus=false; window.dispatchEvent(new Event('blur'))}"
    pg.evaluate("()=>PlaybackApp.setPlaying(true)"); pg.wait_for_timeout(200); print('playing:', playing())
    pg.evaluate(leave); pg.wait_for_timeout(200); print('clicked another tab (focus lost) -> playing:', playing())
    n=len(sent); pg.evaluate("()=>{window.__focus=true}"); pg.mouse.move(400,400); pg.mouse.move(430,420); pg.wait_for_timeout(300)
    print('back on the tab (pointer moves in) -> check_latest sent:', any('check_latest' in s for s in sent[n:]))
    n=len(sent); pg.mouse.move(450,430); pg.wait_for_timeout(200); print('no repeat while staying:', not any('check_latest' in s for s in sent[n:]))
    pg.click('#optBtn'); pg.uncheck('#pauseLeaveChk'); pg.click('#optBtn')
    pg.evaluate("()=>PlaybackApp.setPlaying(true)"); pg.wait_for_timeout(200); pg.evaluate(leave); pg.wait_for_timeout(200)
    print('option off, focus lost -> playing:', playing())
    # blur that keeps focus inside the page (e.g. moving between inputs) must not pause
    pg.evaluate("()=>{window.__focus=true}"); pg.click('#optBtn'); pg.check('#pauseLeaveChk'); pg.click('#optBtn')
    pg.evaluate("()=>{PlaybackApp.setPlaying(true); window.dispatchEvent(new Event('blur'))}"); pg.wait_for_timeout(200)
    print('blur while page still focused -> playing:', playing())
    b.close(); print(errs or 'no errors')
