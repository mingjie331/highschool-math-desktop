import type { QuestionType } from './types'

export interface RecognizedQuestion {
  question: string
  options: string[] | null
  answer: string
  solution: string
  suggestedType: QuestionType | null
  warnings: string[]
}

/** Parse only explicit section markers and option labels at the start of a line. */
export function recognizeQuestion(input: string): RecognizedQuestion {
  const text = input.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n')
  const markers = [...text.matchAll(/【(题目|答案|解析)】/g)]
  if (markers.length === 0 || text.slice(0, markers[0].index).trim()) throw new Error('请从【题目】开始粘贴。')
  const seen = new Set<string>()
  for (const marker of markers) {
    if (seen.has(marker[1])) throw new Error(`“【${marker[1]}】”出现多次，请保留一处。`)
    seen.add(marker[1])
  }
  if (!seen.has('题目') || !seen.has('答案')) throw new Error('粘贴内容必须包含【题目】和【答案】。')
  if (markers.map(marker => marker[1]).join(',') !== (seen.has('解析') ? '题目,答案,解析' : '题目,答案')) {
    throw new Error('请按【题目】、【答案】、【解析】的顺序粘贴。')
  }
  const sections: Record<string, string> = { '题目': '', '答案': '', '解析': '' }
  markers.forEach((marker, index) => {
    sections[marker[1]] = text.slice(marker.index! + marker[0].length, markers[index + 1]?.index ?? text.length).trim()
  })
  const questionLines = sections['题目'].split('\n')
  const answer = sections['答案']
  const solution = sections['解析']
  const warnings: string[] = []
  const starts: { line: number; letter: string; first: string }[] = []
  questionLines.forEach((line, index) => {
    const match = line.match(/^\s*([A-D])\.\s*(.*)$/)
    if (match) starts.push({ line: index, letter: match[1], first: match[2] })
  })
  let question = questionLines.join('\n').trim()
  let options: string[] | null = null
  let suggestedType: QuestionType | null = null
  if (starts.length === 4 && starts.map(item => item.letter).join('') === 'ABCD' && starts[0].line > 0) {
    question = questionLines.slice(0, starts[0].line).join('\n').trim()
    options = starts.map((item, index) => [item.first, ...questionLines.slice(item.line + 1, starts[index + 1]?.line ?? questionLines.length)].join('\n').trim())
    if (options.some(item => !item)) warnings.push('有空选项，请在表单中补全。')
    const letters = answer.replace(/[\s,，、，;；/＋+和与]/g, '').replace(/^\$|\$$/g, '')
    if (/^[A-D]$/.test(letters)) suggestedType = 'single'
    else if (/^[A-D]{2,4}$/.test(letters) && new Set(letters).size === letters.length) suggestedType = 'multi'
    else warnings.push('无法根据答案可靠判断单选或多选，请核对题型。')
  } else if (starts.length) {
    warnings.push('A–D 选项不完整或顺序有误，已保留在题干中，请人工核对。')
  }
  if (!question) warnings.push('题干为空，请补全后正式保存。')
  if (!answer) warnings.push('答案为空，请核对。')
  if (!solution) warnings.push('未提供解析，可先保存草稿；正式保存前需要填写解析。')
  return { question, options, answer, solution, suggestedType, warnings }
}
