const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path')
const {sourcePreferences}=require('../desktop/source-preferences.cjs')
const sid='00000000-0000-0000-0000-000000000001'
test('source preference survives a new application runtime and stays scoped to a conversation',()=>{
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'source-prefs-'))
 try{
  const prefs=sourcePreferences(home);assert.equal(prefs.load(sid),null);prefs.save(sid,{mode:'manual',manual:'人工题源'})
  assert.deepEqual(sourcePreferences(home).load(sid),{mode:'manual',manual:'人工题源'})
  assert.equal(prefs.load('00000000-0000-0000-0000-000000000002'),null)
  assert.throws(()=>prefs.save('../outside',{mode:'auto',manual:''}));assert.throws(()=>prefs.save(sid,{mode:'manual',manual:'x'.repeat(1001)}))
  assert.deepEqual(prefs.load(sid),{mode:'manual',manual:'人工题源'});assert.equal(fs.readdirSync(path.join(home,'.cache/source-preferences')).length,1)
 }finally{fs.rmSync(home,{recursive:true,force:true})}
})
test('damaged preference does not block source entry, write errors are reported',()=>{
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'source-prefs-'))
 try{
  const prefs=sourcePreferences(home);prefs.save(sid,{mode:'auto',manual:''});const file=path.join(home,'.cache/source-preferences',sid+'.json')
  fs.writeFileSync(file,'broken');assert.equal(prefs.load(sid),null);assert.equal(fs.readFileSync(file,'utf8'),'broken')
  fs.unlinkSync(file);fs.mkdirSync(file);assert.throws(()=>prefs.save(sid,{mode:'manual',manual:'保留输入'}))
  assert.ok(fs.statSync(file).isDirectory());assert.equal(fs.readdirSync(path.dirname(file)).length,1)
 }finally{fs.rmSync(home,{recursive:true,force:true})}
})
