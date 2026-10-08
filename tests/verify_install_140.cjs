// Read-only UI checks after startup migration. Never calls the remote provider.
const {_electron:electron}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const home=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);let app
async function main(){
 app=await electron.launch({executablePath:path.join(home,'高中数学题库.exe'),args:[],env:{...process.env,QD_TEST_HIDE_WINDOW:'1',QD_TEST_HOME:home},timeout:60000})
 const page=await app.firstWindow();await page.getByLabel('当前题库',{exact:true}).waitFor({timeout:60000})
 const result=await page.evaluate(async()=>{
  const info=await window.desktop.appInfo()
  const catalog=await(await fetch('/api/catalog?bank_id=system')).json()
  const drafts=await(await fetch('/api/drafts?bank_id=system')).json()
  const config=await window.desktop.agentStatus()
  return {version:info.version,bank_name:catalog.bank_name,questions:catalog.total,drafts:drafts.length,credentials_configured:config.configured,credential_warning:!!config.credential_warning}
 })
 assert.equal(result.version,process.argv[4]||'1.4.0');assert.equal(result.bank_name,'系统题库');assert.equal(await page.getByLabel('当前题库',{exact:true}).inputValue(),'system')
 fs.mkdirSync(path.dirname(out),{recursive:true});fs.writeFileSync(out,JSON.stringify({passed:true,remote_calls:0,...result},null,2));console.log(JSON.stringify(result))
}
main().catch(e=>{console.error(e.message);process.exitCode=1}).finally(async()=>{if(app)await app.close().catch(()=>{})})
