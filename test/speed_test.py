from playwright.sync_api import sync_playwright
html=open('../dist/playback.html').read()
with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-webgl","--ignore-gpu-blocklist"]); errs=[]
    pg=b.new_page(viewport={'width':1300,'height':820}); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.add_init_script("window.__hidden=false;Object.defineProperty(document,'hidden',{get:()=>window.__hidden})")
    pg.route('http://x.local/', lambda r: r.fulfill(body=html, content_type='text/html')); pg.goto('http://x.local/'); pg.wait_for_timeout(300)
    pg.evaluate("t=>PlaybackApp.loadText(t,{name:'b'})", open('bambu.gcode').read()); pg.wait_for_timeout(400)
    rate=lambda: (lambda a: (pg.wait_for_timeout(1000), round(pg.evaluate('()=>PlaybackApp.time')-a,2))[1])(pg.evaluate("()=>{PlaybackApp.seek(20);PlaybackApp.setPlaying(true);return PlaybackApp.time}"))
    pg.select_option('#speedSel','0.5'); print('0.5x: sim seconds per 1s =', rate()); pg.evaluate("()=>PlaybackApp.setPlaying(false)")
    pg.select_option('#speedSel','custom'); pg.fill('#speedCustom','3.7'); pg.press('#speedCustom','Enter')
    print('custom 3.7x:', rate(), '| select shows', pg.eval_on_selector('#speedSel','e=>e.value'), '| box visible', pg.is_visible('#speedCustom')); pg.evaluate("()=>PlaybackApp.setPlaying(false)")
    pg.click('#gl'); pg.keyboard.press('+'); print('+ from 3.7 ->', pg.eval_on_selector('#speedSel','e=>e.value'), '| box visible', pg.is_visible('#speedCustom'))
    pg.keyboard.press('-'); pg.keyboard.press('-'); print('- - ->', pg.eval_on_selector('#speedSel','e=>e.value'))
    # pause on leave option
    def leave_test():
        pg.evaluate("()=>{PlaybackApp.seek(20);PlaybackApp.setPlaying(true)}"); pg.wait_for_timeout(200)
        pg.evaluate("()=>{window.__hidden=true;document.dispatchEvent(new Event('visibilitychange'))}"); pg.wait_for_timeout(200)
        r=pg.evaluate("()=>document.querySelector('#playIco rect')!==null")
        pg.evaluate("()=>{window.__hidden=false;document.dispatchEvent(new Event('visibilitychange'));PlaybackApp.setPlaying(false)}"); return r
    print('pause on leave ON  -> still playing after leaving:', leave_test())
    pg.click('#optBtn'); pg.uncheck('#pauseLeaveChk'); pg.click('#optBtn')
    print('pause on leave OFF -> still playing after leaving:', leave_test())
    pg.select_option('#speedSel','custom'); pg.fill('#speedCustom','0.3'); pg.press('#speedCustom','Enter')
    pg.screenshot(path='shots/s1_speed.png', clip={'x':0,'y':760,'width':700,'height':60}); b.close(); print(errs or 'no errors')
