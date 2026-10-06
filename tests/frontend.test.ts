import { test } from 'node:test'
import assert from 'node:assert/strict'
import { defaultPosition, restoredPosition } from '../frontend/src/position.ts'
import { recognizeQuestion } from '../frontend/src/pasteRecognition.ts'
import type { KnowledgePoint, Question, Draft } from '../frontend/src/types.ts'

const point: KnowledgePoint = { code: '1.1', title: '集合', count: 4, order_revision: 8, questions: [] }
const initial = { collection_code: 'gaoyi-first', point_code: '1.1', position: 2 } as Question

test('returning to the original point keeps a valid position', () => {
  assert.deepEqual(defaultPosition(initial, 'gaoyi-first', point), {
    position: 2, max: 4, context: { position_mode: 'keep', target_order_revision: null },
  })
})
test('new and cross-collection questions append, including colliding point codes', () => {
  assert.equal(defaultPosition(null, 'gaoyi-first', point).position, 5)
  assert.equal(defaultPosition(initial, 'gaoyi-second', point).position, 5)
  assert.equal(defaultPosition(initial, 'gaoyi-second', point).context.target_order_revision, 8)
})
test('old drafts retain current order, cross-point drafts need confirmation', () => {
  const old = { source_question_id: 'question' } as Draft
  assert.equal(restoredPosition(initial, old, 'gaoyi-first', point).position_mode, 'keep')
  assert.deepEqual(restoredPosition(initial, old, 'gaoyi-second', point), { position_mode: 'move', target_order_revision: null })
})
test('explicit draft movement context survives reopening', () => {
  const draft = { source_question_id: 'q', position_mode: 'move', target_order_revision: 7 } as Draft
  assert.deepEqual(restoredPosition(initial, draft, 'gaoyi-first', point), { position_mode: 'move', target_order_revision: 7 })
})
test('existing paste recognition still keeps multiline options and type', () => {
  const value = recognizeQuestion('【题目】\n求值\nA. 一\nB. 二\nC. 三\nD. 四\n【答案】AC\n【解析】说明')
  assert.deepEqual(value.options, ['一', '二', '三', '四'])
  assert.equal(value.suggestedType, 'multi')
})


import { sectionSignatures, currentIssues } from '../frontend/src/reviewChecklist.ts'
import type { AIImportItem } from '../frontend/src/agentTypes.ts'
import type { QuestionPayload } from '../frontend/src/types.ts'
test('viewed section signatures invalidate only affected content', () => {
  const form={type:'fill',question_tex:'题干',options:[],answer_tex:'2',solution_tex:'解析',collection_code:'a',point_code:'1'} as QuestionPayload
  const details={uncertainties:[],figures:[],regions:[],duplicates:[],answer_conflict:false,classification_uncertain:false} as unknown as AIImportItem['details']
  const old=sectionSignatures(form,details,'材料','19',false,false)
  const next=sectionSignatures({...form,answer_tex:'3'},details,'材料','19',false,false)
  assert.equal(old.stem,next.stem);assert.equal(old.figures,next.figures);assert.equal(old.classification,next.classification)
  assert.notEqual(old.answer,next.answer);assert.notEqual(old.layout,next.layout)
})
test('resolving one live warning does not clear unrelated warnings', () => {
  const value={form:{question_tex:'题干'} as QuestionPayload,uncertainties:[],classification_uncertain:false,answer_conflict:true,allow_duplicate:false,figures_confirmed:false,original_number:'19',source_title:'卷子',source_missing:false}
  const issues=currentIssues([{code:'classification',section:'classification',message:'分类'},{code:'answer_conflict',section:'answer',message:'冲突'},{code:'validation',section:'layout',message:'旧错误'}],value,true)
  assert.deepEqual(issues.map(i=>i.code),['answer_conflict'])
})

import {documentPairing} from '../frontend/src/documentPairing.ts'
import type { AIDocument,AIAttachment } from '../frontend/src/agentTypes.ts'
test('combined exam and answers PDF never pairs with itself',()=>{
 const docs=[{id:'d',filename:'四川百师联盟_试卷+答案.pdf'}] as AIDocument[]
 const result=documentPairing(docs,[{id:'p',document_id:'d'}] as AIAttachment[],new Set(['p']),{})
 assert.deepEqual(result.pairs,[]);assert.deepEqual(result.errors,[]);assert.equal(result.values.d,'')
})
test('pair selection and submission use identical state, deselected answer blocks submission',()=>{
 const docs=[{id:'q',filename:'同套_试卷.pdf'},{id:'a',filename:'同套_答案.pdf'}] as AIDocument[]
 const pages=[{id:'p',document_id:'q'},{id:'b',document_id:'a'}] as AIAttachment[]
 const good=documentPairing(docs,pages,new Set(['p','b']),{});assert.equal(good.values.q,'a');assert.equal(good.pairs[0].answer_document_id,'a')
 assert.equal(documentPairing(docs,pages,new Set(['p']),{}).errors.length,1)
 assert.deepEqual(documentPairing(docs,pages,new Set(['p']),{q:''}).pairs,[])
 assert.equal(documentPairing(docs,pages,new Set(['p']),{q:'q'}).errors.length,1)
})

import {sourceDefaults,readSourceChoice,submittedSource} from '../frontend/src/importSource.ts'
test('visible automatic sources preserve per-file backend provenance',()=>{
 const docs=[{id:'q',filename:'卷子_试卷.pdf'},{id:'a',filename:'卷子_答案.pdf'}] as AIDocument[]
 const pages=[{id:'p',document_id:'q',filename:'卷子_试卷.pdf'},{id:'b',document_id:'a',filename:'卷子_答案.pdf'},{id:'i',filename:'截图.PNG'}] as AIAttachment[]
 const pairs=[{question_document_id:'q',answer_document_id:'a'}]
 assert.deepEqual(sourceDefaults(pages,docs,new Set(['p','b','i']),'',pairs),['卷子_试卷','截图'])
 assert.deepEqual(sourceDefaults(pages,docs,new Set(['p','b','i']),'a',pairs),['卷子_试卷'])
 assert.equal(submittedSource({mode:'auto',manual:'手动存值'}),'')
 assert.equal(submittedSource({mode:'manual',manual:'统一题源'}),'统一题源')
})
test('source modes restore safely per conversation without retaining automatic joined names',()=>{
 const store={getItem:(key:string)=>key.endsWith('one')?' {"mode":"manual","manual":"题源A"}':key.endsWith('bad')?'broken':null}
 assert.deepEqual(readSourceChoice(store,'one'),{mode:'manual',manual:'题源A'})
 assert.deepEqual(readSourceChoice(store,'two'),{mode:'auto',manual:''});assert.deepEqual(readSourceChoice(store,'bad'),{mode:'auto',manual:''})
})

test('automatic defaults collapse PDF pages and exclude unselected or answer-only files',()=>{
 const docs=[{id:'q',filename:'综合_试卷+答案.pdf'},{id:'a',filename:'答案.pdf'}] as AIDocument[]
 const pages=[{id:'p1',document_id:'q',filename:docs[0].filename},{id:'p2',document_id:'q',filename:docs[0].filename},{id:'a1',document_id:'a',filename:docs[1].filename}] as AIAttachment[]
 assert.deepEqual(sourceDefaults(pages,docs,new Set(['p1','p2','a1']),'',[]),['综合_试卷+答案'])
 assert.deepEqual(sourceDefaults(pages,docs,new Set(['a1']),'',[]),[])
 assert.deepEqual(sourceDefaults(pages,docs,new Set(),'q',[]),[])
})
