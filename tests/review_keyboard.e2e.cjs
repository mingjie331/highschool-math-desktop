// No provider calls: exercise focus, width controls and menu on isolated candidates.
const {_electron:electron}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict')
const root=path.resolve(__dirname,'..'),output=path.join(root,'test-results/review-keyboard')
fs.mkdirSync(output,{recursive:true});const home=fs.mkdtempSync(path.join(output,'run-'));const checks=[];let app
async function main(){
 app=await electron.launch({args:[path.join(root,'tests/electron_review_fixture.cjs')],env:{...process.env,QD_TEST_HOME:home,QD_TEST_HIDE_WINDOW:'1'},timeout:60000})
 const page=await app.firstWindow();await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.setBackgroundThrottling(false))
 await page.getByRole('button',{name:'AI 录题',exact:true}).click();await page.getByRole('tab',{name:/待核对/}).click()
 await page.getByLabel('待核对题目列表').getByRole('button',{name:/^第 /}).first().click();await page.getByLabel('核对清单').waitFor()
 const separator=page.getByRole('separator',{name:'调整对照宽度'});await separator.focus();await separator.press('ArrowRight')
 await page.waitForFunction(()=>document.querySelector('.ai-divider').getAttribute('aria-valuenow')==='52')
 await separator.press('ArrowLeft');await page.waitForFunction(()=>document.querySelector('.ai-divider').getAttribute('aria-valuenow')==='50')
 checks.push({name:'keyboard_resize_and_restore',passed:true})
 const figures=page.getByLabel('核对清单').getByRole('button',{name:/^配图/});await figures.focus();await figures.press('Enter')
 await page.waitForFunction(()=>document.querySelector('.ai-checklist button:nth-child(2)').getAttribute('aria-pressed')==='true')
 await page.getByRole('button',{name:'补充配图',exact:true}).waitFor()
 const menu=page.locator('.ai-more summary');await menu.focus();await menu.press('Enter');assert.equal(await page.locator('.ai-more').evaluate(e=>e.open),true)
 await menu.press('Tab');assert.equal(await page.getByRole('button',{name:'调整题目范围',exact:true}).evaluate(e=>e===document.activeElement),true)
 await menu.focus();await menu.press('Enter');assert.equal(await page.locator('.ai-more').evaluate(e=>e.open),false)
 checks.push({name:'checklist_and_menu_keyboard_focus',passed:true})
 await page.getByRole('button',{name:'放大工作区',exact:true}).click();assert.equal(await page.locator('.ai-review-result').isVisible(),false)
 await page.getByRole('button',{name:'恢复对照',exact:true}).click();assert.equal(await page.locator('.ai-review-result').isVisible(),true)
 checks.push({name:'expand_canvas_restore_comparison',passed:true})
 const child=app.process(),exited=new Promise(resolve=>child.once('exit',resolve));await app.evaluate(({app})=>app.quit());assert.equal(await exited,0);app=null
}
main().catch(e=>{checks.push({name:'failure',passed:false,error:e.message});console.error(e.stack);process.exitCode=1}).finally(async()=>{if(app)await app.close().catch(()=>{});fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({remote_calls:0,checks},null,2));console.log(JSON.stringify(checks))})
