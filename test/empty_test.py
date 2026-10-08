import sys, json, re
from playwright.sync_api import sync_playwright
html=open('../dist/playback.html').read()
src=open('../src/plugin.py').read()
hint=eval(re.search(r'SETUP_HINT = (\{.*?\n\})', src, re.S).group(1))
out=sys.argv[1]
with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-webgl","--ignore-gpu-blocklist"])
    for w,h,tag in [(1300,820,'wide'),(760,620,'narrow')]:
        pg=b.new_page(viewport={'width':w,'height':h}); pg.set_content(html); pg.wait_for_timeout(300)
        pg.evaluate("h=>PlaybackApp.onHostMessage({cmd:'status', capture_enabled:false, hint:h})", hint); pg.wait_for_timeout(200)
        pg.screenshot(path=f'shots/{out}_{tag}.png')
        print(tag, pg.evaluate("""()=>{const b=document.querySelector('#empty .box').getBoundingClientRect(); return [...document.querySelectorAll('#empty .box *')].filter(e=>{const r=e.getBoundingClientRect(); return r.width&&(r.right>b.right+1||r.left<b.left-1)}).map(e=>e.tagName+'.'+e.className).slice(0,5)}"""))
    b.close()
