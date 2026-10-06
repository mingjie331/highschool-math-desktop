export type QuestionType = 'single' | 'multi' | 'fill' | 'long'

export interface QuestionSummary {
  id: string
  local_number: number
  type: QuestionType
  type_name: string
  preview: string
  revision: number
}

export interface KnowledgePoint {
  code: string
  title: string
  count: number
  order_revision: number
  questions: QuestionSummary[]
}

export interface Topic {
  code: string
  title: string
  count: number
  points: KnowledgePoint[]
}

export interface Catalog {
  revision: number
  total: number
  collections: Collection[]
  semesters: Collection[]
  topics: Topic[]
}

export interface Collection {
  code: string
  title: string
  material: string
  count: number
  topics: Topic[]
}

export interface QuestionOrigin {
  title: string
  original_number?: string | number
  [key: string]: unknown
}

export interface QuestionSources {
  origins?: QuestionOrigin[]
  source_missing?: boolean
  [key: string]: unknown
}

export interface Question {
  id: string
  legacy_uid: string | null
  collection_code: string
  point_code: string
  position: number
  type: QuestionType
  question_tex: string
  options: string[]
  answer_tex: string
  solution_tex: string
  sources: QuestionSources
  verified: boolean
  revision: number
  order_revision: number | null
  created_at: string
  updated_at: string
}

export interface QuestionPayload {
  collection_code: string
  point_code: string
  position: number
  type: QuestionType
  question_tex: string
  options: string[]
  answer_tex: string
  solution_tex: string
  sources: QuestionSources
  verified: boolean
  revision?: number
  position_mode?: 'keep' | 'move' | null
  target_order_revision?: number | null
}

export interface ExportStatus {
  collection_code: string
  current_count: number
  collection_revision: number | null
  question_filename: string
  solution_filename: string
  available?: boolean
  state: 'idle' | 'pending' | 'building' | 'ready' | 'failed'
  stale: boolean
  message: string
  updated_at: string | null
  catalog_revision: number | null
  count: number
  error?: string | null
  question_pdf: string
  solution_pdf: string
}

export interface SourceDraft { title: string; originalNumber: string; metadata: Record<string, unknown> }
export type DraftForm = Omit<QuestionPayload, 'position'> & { position: string | number | null }
export interface DraftContent { form: DraftForm; source_rows: SourceDraft[] }
export interface Draft {
  id: string
  source_question_id: string | null
  base_revision: number | null
  position_mode?: 'keep' | 'move' | null
  target_order_revision?: number | null
  content: DraftContent
  revision: number
  created_at: string
  updated_at: string
}
export interface SearchResult {
  id: string; local_number: number; type: QuestionType; type_name: string
  collection_code: string; collection_title: string
  topic_code: string; topic_title: string; point_code: string; point_title: string; snippet: string
}

export interface PoolItem extends Question { added_order: number; preview: string }
export interface PoolState { items: PoolItem[]; count: number; limit: number; can_undo: boolean; undo_count: number }
export interface PaperStatus {
  state: 'idle' | 'pending' | 'building' | 'ready' | 'failed'
  message: string
  error: string | null
  available: boolean
  generation: string | null
  generated_at: string | null
  count: number
  files: { question?: string; solution?: string }
}
