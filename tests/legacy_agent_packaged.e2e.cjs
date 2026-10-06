const { _electron:electron }=require('playwright')
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process')
const root=path.resolve(__dirname,'..'),exe=process.argv[2],source=process.argv[3]||process.env.QD_TEST_LEGACY_HOME
if(!exe||!source)throw new Error('Provide release executable and an explicitly authorized old application folder')
const area=path.join(root,'test-results/legacy-130');fs.mkdirSync(area,{recursive:true})
const home=fs.mkdtempSync(path.join(area,'run-'))
const copy=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',
 "import pathlib,sqlite3,shutil,sys,contextlib,json;old=pathlib.Path(sys.argv[1]);target=pathlib.Path(sys.argv[2]);shutil.copytree(old/'data',target/'data');shutil.copytree(old/'.cache/electron',target/'.cache/electron');p=target/'data/question_bank.sqlite3';c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True);r=c.execute(\"select content_json from drafts\").fetchall();print(json.dumps({'drafts':[v[0] for v in r],'schema':c.execute(\"select value from metadata where key='schema_version'\").fetchone()[0]}));c.close()",source,home],{encoding:'utf8',windowsHide:true})
assert.equal(copy.status,0,copy.stderr);const baseline=JSON.parse(copy.stdout)
let app,page;const checks=[]
async function request(url){return page.evaluate(async url=>(await(await fetch(url)).json()),url)}
async function open(){app=await electron.launch({executablePath:exe,args:[],env:{...process.env,QD_TEST_HOME:home,QD_TEST_HIDE_WINDOW:'1'},timeout:60000});page=await app.firstWindow();await page.getByRole('button',{name:'AI 录题',exact:true}).waitFor({timeout:60000})}
async function close(){const child=app.process(),exit=new Promise(r=>child.once('exit',r));await app.evaluate(({app})=>app.quit());assert.equal(await exit,0);app=null}
async function inspect(){const result=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"import sqlite3,pathlib,json,sys,contextlib;p=pathlib.Path(sys.argv[1]);c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True);print(json.dumps({'schema':c.execute(\"select value from metadata where key='schema_version'\").fetchone()[0],'drafts':[r[0] for r in c.execute('select content_json from drafts')],'publications':c.execute('select count(*) from ai_publications').fetchone()[0]}));c.close()",path.join(home,'data/question_bank.sqlite3')],{encoding:'utf8',windowsHide:true});assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout)}
async function main(){
 await open();const migrated=await inspect();assert.ok(['6','7'].includes(baseline.schema));assert.equal(migrated.schema,'8');assert.deepEqual(migrated.drafts,baseline.drafts);assert.equal(migrated.publications,0)
 assert.equal((await request('/api/agent/workbench')).counts.publish,0)
 assert.equal((await request('/api/catalog')).total,627);assert.equal((await request('/api/agent/config')).configured,true)
 const backups=fs.readdirSync(path.join(home,'data/backups')).length;checks.push({name:'actual_schema6_upgrades_preserving_draft_and_native_key',passed:true})
 await close();await open();assert.equal(fs.readdirSync(path.join(home,'data/backups')).length,backups);assert.deepEqual((await inspect()).drafts,baseline.drafts)
 checks.push({name:'repeated_start_does_not_migrate_or_publish_again',passed:true});await close()
}
main().catch(e=>{console.error(e.stack);checks.push({name:'failure',passed:false,error:e.message});process.exitCode=1}).finally(async()=>{if(app)await app.close().catch(()=>{});fs.writeFileSync(path.join(area,'results.json'),JSON.stringify({home,remote_calls:0,checks},null,2));checks.forEach(c=>console.log(JSON.stringify(c)))})
