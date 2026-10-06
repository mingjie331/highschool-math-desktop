import type { QuestionPayload } from './types'

export interface AIConfigStatus { configured: boolean; base_url: string; model: string; prices: Record<string, number>; price_note: string; credential_warning?: string }
export interface AIMessage { id: string; role: 'user' | 'assistant'; content: string; created_at: string }
export interface AIRegion { image_id: string; rect: [number, number, number, number]; role?: 'question' | 'answer' | 'solution' }
export interface AIAttachment { id: string; filename: string; sha256: string; width: number; height: number; url: string; document_id?: string | null; page_number?: number; kind?: string }
export interface AIDocument { id: string; filename: string; page_count: number; kind: 'pdf'; url: string; pages?: AIAttachment[] }
export interface AIImportItem {
  id: string; task_id: string; draft_id: string; item_order: number; revision: number; state: string;
  form: QuestionPayload; question_id: string | null;
  draft_revision: number | null; validation_current?: boolean;
  reviewed_at: string | null; reviewed_hash: string | null; review_stage: AIReviewStage; issues: AIReviewIssue[];
  details: {
    regions: AIRegion[]; figures: (AIRegion & { id: string; field: string; asset_path?: string })[];
    classification_reason: string; classification_candidates: { collection_code: string; point_code: string; reason: string }[];
    classification_uncertain: boolean; uncertainties: string[]; answer_conflict: boolean; alternative_answer?: string;
    answer_origin: 'original' | 'ai' | 'missing' | 'edited'; solution_origin: 'original' | 'ai' | 'missing' | 'edited';
    original_number: string; validation_error?: string | null; allow_duplicate: boolean;
    format_repair_count?: number;
    figures_confirmed?: boolean; expected_figures?: number; figure_issues?: string[];
    stage_error?: { stage: string; code: string; message: string; max_tokens?: number } | null;
    duplicates: { id: string; candidate?: boolean; collection_code?: string; point_code?: string; position?: number; exact: boolean }[];
  }
}
export type AIReviewStage = 'processing' | 'review' | 'publish' | 'published' | 'skipped' | 'failed' | 'deleted'
export interface AIReviewIssue { code: string; section: 'stem' | 'figures' | 'answer' | 'classification' | 'layout'; message: string; field?: string | null; target?: { field?: string; figure_id?: string; image_id?: string; rect?: AIRegion['rect'] }; action?: string }
export interface AIQueueItem { id: string; task_id: string; session_id: string; task_title: string; item_order: number; revision: number; state: string; review_stage: AIReviewStage; original_number: string; summary: string; type: string; collection_code: string; point_code: string; source_title: string; question_id: string | null; issues: AIReviewIssue[] }
export interface AITaskSummary { id: string; session_id: string; message: string; state: string; error?: string | null; created_at: string; worker_active: boolean; filenames: string[]; page_count: number; counts: Record<AIReviewStage, number>; sources: string[] }
export interface AIWorkbenchData { counts: Record<AIReviewStage, number>; tasks: AITaskSummary[]; items: AIQueueItem[]; total: number; offset: number; limit: number }
export interface AIFailure { id:string; item_id?:string; original_number:string; stage:string; code:string; message:string; regions:AIRegion[]; sources?:{filename:string;page_number:number;rect:AIRegion['rect']}[] }
export interface AIImportTask {
  failures:AIFailure[]; failure_count:number; deleted_count:number;
  id: string; session_id: string; state: string; message: string; error: string | null; revision: number;
  created_at: string; updated_at: string;
  worker_active: boolean;
  payload: { attachment_ids: string[]; instruction: string; source_title?: string };
  items: AIImportItem[]; calls: number; usage: Record<string, number>; estimated_cost_cny: number; cost_note: string;
}
export type AITaskProgress = Omit<AIImportTask, 'items'> & { items: Pick<AIImportItem, 'id' | 'question_id' | 'state' | 'revision' | 'review_stage'>[] }
export interface AIConversation { id: string; title: string; created_at: string; updated_at: string; messages: AIMessage[]; attachments: AIAttachment[]; documents?: AIDocument[]; tasks: AIImportTask[] }
