const {_electron:electron}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync,spawn}=require('node:child_process')
const root=path.resolve(__dirname,'..'),area=path.join(root,'test-results/update-exit-134');fs.mkdirSync(area,{recursive:true})
const home=fs.mkdtempSync(path.join(area,'run-')),source=require('./private_paths.cjs').oldApp,checks=[];let app
if(!source)throw new Error('Provide --old-app or QD_TEST_OLD_APP for the isolated exit/update test')
for(const file of fs.readdirSync(source)){if(['data','.cache','output','logs','app-files.json'].includes(file))continue;fs.cpSync(path.join(source,file),path.join(home,file),{recursive:true})}
const seed=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"import pathlib,json,sys,hashlib;home=pathlib.Path(sys.argv[1]);files=[{'path':p.relative_to(home).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in home.rglob('*') if p.is_file()];(home/'app-files.json').write_text(json.dumps({'version':'1.3.3','schema':8,'files':files},ensure_ascii=False),encoding='utf-8')",home],{encoding:'utf8',windowsHide:true});assert.equal(seed.status,0,seed.stderr)
function update(timeout){return new Promise(resolve=>{const child=spawn('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-File',path.join(root,'scripts/update_app.ps1'),'-Worker','-Target',home,'-BackupRoot',path.join(area,'backups'),'-Package',path.join(root,'build/release-stage/1.3.4/高中数学题库-1.3.4-Windows-x64.zip'),'-CloseTimeoutSeconds',String(timeout)],{windowsHide:true});let text='';child.stdout.on('data',d=>text+=d);child.stderr.on('data',d=>text+=d);child.on('exit',code=>resolve({code,text}))})}
async function main(){
 app=await electron.launch({executablePath:path.join(home,'高中数学题库.exe'),args:[],env:{...process.env,QD_TEST_HOME:home,QD_TEST_HIDE_WINDOW:'1'},timeout:60000})
 const page=await app.firstWindow();await page.getByRole('button',{name:'AI 录题',exact:true}).waitFor({timeout:60000})
 const current=fs.readFileSync(path.join(home,'resources/app.asar'))
 const failed=await update(2);assert.notEqual(failed.code,0);assert.ok(fs.readFileSync(path.join(home,'resources/app.asar')).equals(current));assert.equal(app.process().exitCode,null)
 checks.push({name:'unfinished_exit_aborts_without_forcing_or_replacing_program',passed:true});console.log(JSON.stringify(checks.at(-1)))
 const before=await page.evaluate(async()=>await(await fetch('/api/catalog')).json())
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].showInactive())
 const child=app.process(),exit=new Promise(r=>child.once('exit',r));const success=await update(30)
 assert.equal(success.code,0,success.text);assert.equal(await exit,0);app=null
 const inspect=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute('SELECT count(*) FROM questions').fetchone()[0])",path.join(home,'data/question_bank.sqlite3')],{encoding:'utf8',windowsHide:true});assert.equal(Number(inspect.stdout.trim()),before.total)
 checks.push({name:'normal_close_stops_backend_then_updates_and_preserves_bank',passed:true});console.log(JSON.stringify(checks.at(-1)))
}
main().catch(e=>{console.error(e.stack);checks.push({name:'failure',passed:false,error:e.message});process.exitCode=1}).finally(async()=>{if(app)await app.close().catch(()=>{});fs.writeFileSync(path.join(area,'results.json'),JSON.stringify({paid_calls:0,checks},null,2))})
