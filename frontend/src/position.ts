import type { Catalog, Draft, KnowledgePoint, Question } from './types'

export interface PositionContext {
  position_mode: 'keep' | 'move' | null
  target_order_revision: number | null
}

export function samePoint(initial: Question | null, collection: string, point: string): boolean {
  return !!initial && initial.collection_code === collection && initial.point_code === point
}

export function targetPoint(catalog: Catalog, collection: string, point: string): KnowledgePoint | undefined {
  return catalog.collections.find(item => item.code === collection)?.topics.flatMap(item => item.points).find(item => item.code === point)
}

export function defaultPosition(initial: Question | null, collection: string, point: KnowledgePoint) {
  const keep = samePoint(initial, collection, point.code)
  return {
    position: keep ? initial!.position : point.count + 1,
    max: point.count + (keep ? 0 : 1),
    context: { position_mode: keep ? 'keep' : 'move', target_order_revision: keep ? null : point.order_revision } as PositionContext,
  }
}

export function restoredPosition(initial: Question | null, draft: Draft | null, collection: string, point: KnowledgePoint): PositionContext {
  if (draft?.position_mode) return { position_mode: draft.position_mode, target_order_revision: draft.target_order_revision ?? null }
  if (draft?.source_question_id) return { position_mode: samePoint(initial, collection, point.code) ? 'keep' : 'move', target_order_revision: null }
  return defaultPosition(initial, collection, point).context
}
