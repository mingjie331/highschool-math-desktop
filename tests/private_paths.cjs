const path=require('node:path'),fs=require('node:fs')
const root=path.resolve(__dirname,'..')
function argument(name){const n=process.argv.indexOf(name);return n>=0?process.argv[n+1]:undefined}
const materials=path.resolve(argument('--materials')||process.env.QD_TEST_MATERIALS||process.env.QD_LIVE_MATERIALS||path.join(root,'.local/test-materials'))
const snapshots=path.resolve(process.env.QD_TEST_SNAPSHOTS||path.join(root,'.local/backups/test-snapshots'))
const liveArea=path.resolve(process.env.QD_TEST_LIVE_AREA||path.join(snapshots,'agent-120-live'))
const candidateData=process.env.QD_TEST_DATA?path.resolve(process.env.QD_TEST_DATA):path.join(liveArea,'home/data')
function readRuns(){
 const value=JSON.parse(fs.readFileSync(path.join(liveArea,'runs.json'),'utf8'))
 const old=path.join(root,'.cache/agent-120-live')
 const remap=v=>typeof v==='string'?(v.replaceAll(old,liveArea).replaceAll(old.replaceAll('\\','/'),liveArea.replaceAll('\\','/'))):Array.isArray(v)?v.map(remap):v&&typeof v==='object'?Object.fromEntries(Object.entries(v).map(([k,x])=>[k,remap(x)])):v
 return remap(value)
}
const oldApp=argument('--old-app')||process.env.QD_TEST_OLD_APP
module.exports={materials,snapshots,liveArea,candidateData,readRuns,oldApp:oldApp?path.resolve(oldApp):undefined}
