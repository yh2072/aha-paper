import json,sys
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
root=Path(__file__).resolve().parents[1]
fixture=root/'web/demo'
manifest=json.loads((fixture/'experience.json').read_text())
manifest['video']='/assets/demo/media/video.mp4';manifest['cover']='/assets/demo/media/cover.png'
import tempfile
out=Path(tempfile.mkdtemp(prefix='aha-paper-overlay-'))
with sync_playwright() as p:
 browser=p.chromium.launch(channel='chrome',headless=True)
 page=browser.new_page(viewport={'width':1440,'height':1000})
 page.set_default_timeout(8000)
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.route('**/api/projects/aha-paper_brain-guided-reasoning/experience',lambda r:r.fulfill(json=manifest))
 page.route('**/watch/aha-paper_brain-guided-reasoning',lambda r:r.fulfill(body=(root/'web/watch.html').read_text(),content_type='text/html'))
 page.goto('http://localhost:8321/watch/aha-paper_brain-guided-reasoning');page.wait_for_selector('.chapter')
 page.locator('.chapter').nth(1).click();page.locator('#openGame').click()
 assert page.locator('video').evaluate('(v)=>v.paused && v.inert')
 assert page.locator('#gamePanel').evaluate('(g)=>g.closest(".video-shell")!==null')
 box=page.locator('.video-shell').bounding_box();game=page.locator('#gamePanel').bounding_box()
 assert game['x']>=box['x'] and game['y']>=box['y']
 assert game['x']+game['width']<=box['x']+box['width']+1
 correct=next(o for o in manifest['segments'][1]['game']['options'] if o['correct'])
 page.locator('[data-option="'+correct['id']+'"]').click();page.locator('#checkGame').click()
 assert page.locator('#score').inner_text()=='1'
 page.screenshot(path=str(out/'overlay-desktop.png'))
 page.locator('#closeGame').click();page.locator('#fullscreen').click();page.wait_for_function('document.fullscreenElement !== null');page.locator('#floatingGame').click();assert page.locator('#gamePanel').is_visible();assert page.locator('#gamePanel').evaluate('(g)=>document.fullscreenElement.contains(g)');page.locator('#closeGame').click();page.evaluate('document.exitFullscreen()');page.locator('#openGame').click();page.keyboard.press('Escape');assert page.locator('#gamePanel').is_hidden()
 assert not page.locator('video').evaluate('(v)=>v.inert')
 page.set_viewport_size({'width':390,'height':844});page.locator('#openGame').click()
 assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 page.screenshot(path=str(out/'overlay-mobile.png'))
 assert not errors,errors
 browser.close()
print('PASS: default overlay, pause/inert, answer, fullscreen, Escape, and desktop/mobile containment')
