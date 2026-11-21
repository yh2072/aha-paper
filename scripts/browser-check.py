"""Browser integration checks against the local, rendered smoke experience."""
import json
import zipfile
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
smoke=root/'data/smoke'
base='http://127.0.0.1:8322'
manifest=json.loads((smoke/'experience.json').read_text())
errors=[]
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1100})
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(base+'/')
    page.wait_for_selector('.project')
    assert page.get_by_role('link',name='进入互动视频',exact=False).count()==1
    page.screenshot(path=str(smoke/'aha-paper-studio.png'),full_page=True)
    page.get_by_role('link',name='进入互动视频',exact=False).click()
    page.wait_for_selector('.chapter')
    page.wait_for_function('document.querySelector("video").readyState>=1')
    chapters=page.locator('.chapter')
    assert chapters.count()==2
    chapters.nth(1).click()
    page.wait_for_timeout(500)
    assert abs(page.locator('video').evaluate('(v)=>v.currentTime')-manifest['segments'][1]['start'])<1.5
    page.get_by_role('button',name='玩一玩这一章',exact=False).click()
    game=manifest['segments'][1]['game']
    assert game['kind']=='predict'
    correct=next(o for o in game['options'] if o['correct'])
    page.locator('[data-option="'+correct['id']+'"]').click()
    page.locator('#checkGame').click()
    assert page.locator('#score').inner_text()=='1'
    assert page.locator('#evidenceBox').is_visible()
    page.screenshot(path=str(smoke/'aha-paper-interactive.png'),full_page=True)
    page.reload();page.wait_for_selector('.chapter');assert page.locator('#score').inner_text()=='1'
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(smoke/'aha-paper-interactive-mobile.png'),full_page=True)
    # Test the other generated-game interaction templates with deterministic fixtures.
    order_game={'kind':'order','title':'把流程排好','instructions':'先准备，再观察，最后总结',
        'items':[{'id':c,'label':label}for c,label in zip('abc',['准备','观察','总结'])],
        'correct_order':list('abc'),'explanation':'三个步骤按原顺序进行。','evidence':'先准备，再观察，最后总结。'}
    fixture=json.loads(json.dumps(manifest));fixture['id']='order-fixture';fixture['segments'][0]['game']=order_game
    page.route('**/api/projects/order-fixture/experience',lambda route:route.fulfill(json=fixture))
    page.route('**/watch/order-fixture',lambda route:route.fulfill(body=(root/'web/watch.html').read_text(),content_type='text/html'))
    page.goto(base+'/watch/order-fixture');page.wait_for_selector('.chapter');page.locator('#openGame').click()
    for destination,item_id in enumerate('abc'):
        for _ in range(5):
            labels=page.locator('.order-label').all_text_contents();current=labels.index({'a':'准备','b':'观察','c':'总结'}[item_id])
            if current==destination:break
            page.locator(f'[data-move="up"][data-at="{current}"]').click()
    page.locator('#checkGame').click();assert page.locator('#score').inner_text()=='1'
    pairs=[{'id':str(i),'left':x,'right':y}for i,(x,y)in enumerate([('输入','材料'),('过程','分析'),('输出','结论')])]
    fixture['id']='match-fixture';fixture['segments'][0]['game']={'kind':'match','title':'把概念配对','instructions':'点击左右两边','pairs':pairs,'explanation':'概念各有定义。','evidence':'原句'}
    page.route('**/api/projects/match-fixture/experience',lambda route:route.fulfill(json=fixture))
    page.route('**/watch/match-fixture',lambda route:route.fulfill(body=(root/'web/watch.html').read_text(),content_type='text/html'))
    page.goto(base+'/watch/match-fixture');page.wait_for_selector('.chapter');page.locator('#openGame').click()
    for i in range(3):
        page.locator(f'[data-left="{i}"]').click();page.locator(f'[data-right="{i}"]').click()
    page.locator('#checkGame').click();assert page.locator('#score').inner_text()=='1'
    # An exported experience works without the API, including local media and game logic.
    offline=smoke/'offline'
    with zipfile.ZipFile(smoke/'aha-paper-interactive.zip') as archive:archive.extractall(offline)
    page.goto((offline/'index.html').as_uri());page.wait_for_selector('.chapter')
    page.wait_for_function('document.querySelector("video").readyState>=1')
    assert page.locator('.chapter').count()==2
    assert page.locator('#downloadBundle').is_hidden()
    browser.close()
assert not errors,errors
print('PASS: chapter seeking, prediction/scoring/persistence, sorting, matching, mobile layout, offline video package; no browser script errors')
