import type { AIImportItem, AIReviewIssue } from './agentTypes'
import type { QuestionPayload } from './types'
export const reviewSections = ['stem','figures','answer','classification','layout'] as const
export type ReviewSection = typeof reviewSections[number]
export const sectionNames = {stem:'题干与选项',figures:'配图',answer:'答案解析',classification:'分类与题源',layout:'排版检查'}
// These compact fingerprints track viewing only; the server SHA-256 guards approval.
const signature=(value:unknown)=>{
 const text=JSON.stringify(value);let a=2166136261,b=5381
 for(let i=0;i<text.length;i++){a=Math.imul(a^text.charCodeAt(i),16777619);b=Math.imul(b,33)^text.charCodeAt(i)}
 return `${text.length}:${(a>>>0).toString(16)}:${(b>>>0).toString(16)}`
}
export function sectionSignatures(form:QuestionPayload, details:AIImportItem['details'], source:string, number:string, missing:boolean, validation:boolean) {
  const notes=(section:string)=>details.uncertainties.filter(m=>(m.includes('配图')?'figures':/题号|分类/.test(m)?'classification':/答案|解析/.test(m)?'answer':'stem')===section)
  return {
    stem:signature([form.type,form.question_tex,form.options,details.duplicates,details.allow_duplicate,notes('stem')]),
    figures:signature([details.regions,details.figures,details.figure_issues,details.expected_figures,details.figures_confirmed,notes('figures')]),
    answer:signature([form.answer_tex,form.solution_tex,details.answer_conflict,details.alternative_answer,notes('answer')]),
    classification:signature([form.collection_code,form.point_code,source,number,missing,details.classification_uncertain,notes('classification')]),
    layout:signature([form.question_tex,form.options,form.answer_tex,form.solution_tex,details.figures,validation,details.validation_error])
  }
}
export function currentIssues(issues:AIReviewIssue[], value:{form:QuestionPayload;uncertainties:string[];classification_uncertain:boolean;answer_conflict:boolean;allow_duplicate:boolean;figures_confirmed:boolean;original_number:string;source_title:string;source_missing:boolean}, dirty:boolean) {
  return issues.filter(i=>{
    if(i.code==='missing_stem')return !value.form.question_tex.trim()
    if(i.code==='missing_options')return ['single','multi'].includes(value.form.type)&&(value.form.options.length!==4||value.form.options.some(v=>!v.trim()))
    if(i.code==='missing_answer')return !value.form.answer_tex.trim()
    if(i.code==='missing_solution')return !value.form.solution_tex.trim()
    if(i.code==='missing_number')return !value.original_number.trim()
    if(i.code==='missing_source')return !value.source_title.trim()&&!value.source_missing
    if(i.code==='classification')return value.classification_uncertain
    if(i.code==='answer_conflict')return value.answer_conflict
    if(i.code==='duplicates')return !value.allow_duplicate
    if(i.code==='figure_confirmation')return !value.figures_confirmed
    if(i.code.startsWith('uncertainty:'))return value.uncertainties.includes(i.message)
    if(i.code==='validation'&&dirty)return false
    return true
  }).sort((a,b)=>reviewSections.indexOf(a.section)-reviewSections.indexOf(b.section))
}
