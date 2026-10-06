const {_electron:electron}=require('playwright'),fs=require('node:fs'),path=require('node:path')
const root=path.resolve(__dirname,'..'),area=require('./private_paths.cjs').liveArea,runs=require('./private_paths.cjs').readRuns()
const ids=['cd513401-19bc-40d5-9e35-58ac4b2e9bbd','97eb010e-a8b3-4ff1-bfb4-cf0e45d13254','506ac4ea-b5e7-4bdb-b376-c49e4e44ceba']
let app,page
async function request(url,method='GET'){return page.evaluate(async({url,method})=>{const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:method==='POST'?'{}':undefined});const value=await r.json();if(!r.ok)throw new Error(JSON.stringify(value));return value},{url,method})}
async function main(){
 app=await electron.launch({executablePath:process.argv[2],args:[],env:{...process.env,QD_TEST_HOME:runs.home,QD_TEST_HIDE_WINDOW:'1'},timeout:60000});page=await app.firstWindow();await page.getByRole('button',{name:'AI 录题',exact:true}).waitFor({timeout:60000})
 const output=[]
 for(const id of ids){
  const task=await request('/api/agent/imports/'+id)
  for(let i=0;i<task.items.length;i+=3)await Promise.all(task.items.slice(i,i+3).filter(item=>!['published','skipped'].includes(item.state)).map(item=>request('/api/agent/items/'+item.id+'/validate','POST')))
  const final=await request('/api/agent/imports/'+id);output.push(final);console.log(JSON.stringify({task:id,items:final.items.length,ready:final.items.filter(i=>i.state==='ready').length,review:final.items.filter(i=>i.state==='needs_review').length,published:final.items.filter(i=>i.state==='published').length}))
 }
 // Typed candidates only, no provider's raw responses or credentials.
 fs.writeFileSync(path.join(area,'final-candidates.json'),JSON.stringify(output,null,2))
 const child=app.process(),exit=new Promise(r=>child.once('exit',r));await app.evaluate(({app})=>app.quit());await exit;app=null
}
main().catch(e=>{console.error(e.message);process.exitCode=1}).finally(async()=>{if(app)await app.close().catch(()=>{})})
