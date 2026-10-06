import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import type { Draft, DraftContent, Question } from './types'
import type { PositionContext } from './position'

function canonical(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']'
  if (value && typeof value === 'object') return '{' + Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => JSON.stringify(key) + ':' + canonical(item)).join(',') + '}'
  return JSON.stringify(value)
}

// One writer per editor. A save drains to the latest input, never an old closure.
export function useDraft(content: DraftContent, initial: Question | null, draft: Draft | null, position: PositionContext) {
  const [status, setStatus] = useState(draft ? '已恢复草稿' : '修改后自动保存草稿')
  const id = useRef(draft?.id || crypto.randomUUID())
  const revision = useRef(draft?.revision || 0)
  const source = useRef(draft?.source_question_id || initial?.id || null)
  const base = useRef(draft?.base_revision || initial?.revision || null)
  const latest = useRef({ content, position })
  latest.current = { content, position }
  const encoded = JSON.stringify(latest.current)
  // Compare restored defaults against the persisted acknowledgement, so legacy
  // drafts also save their adopted positioning policy before publication.
  const saved = useRef(draft ? JSON.stringify({ content: draft.content, position: {
    position_mode: draft.position_mode ?? null, target_order_revision: draft.target_order_revision ?? null,
  } }) : encoded)
  const pending = useRef<Promise<void> | null>(null)
  const closed = useRef(false)
  const paused = useRef(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const report = (text: string) => { if (mounted.current) setStatus(text) }

  const flush = (force = false): Promise<void> => {
    if (closed.current) return Promise.resolve()
    if (pending.current) return pending.current
    const run = async () => {
      while (!closed.current && (JSON.stringify(latest.current) !== saved.current || (force && revision.current === 0))) {
        const snapshot = structuredClone(latest.current)
        const sent = JSON.stringify(snapshot)
        report('正在保存草稿…')
        const expected = revision.current
        let result: Draft
        try {
          result = await api.saveDraft(id.current, expected, source.current, base.current, snapshot.content, snapshot.position)
        } catch (error) {
          // A transport error can happen after SQLite commits. Recover that exact
          // acknowledgement, then drain newer input instead of overwriting it.
          const remote = await api.draft(id.current).catch(() => null)
          if (!remote || remote.revision !== expected + 1 || canonical(remote.content) !== canonical(snapshot.content)
              || (remote.position_mode ?? null) !== snapshot.position.position_mode
              || (remote.target_order_revision ?? null) !== snapshot.position.target_order_revision) throw error
          result = remote
        }
        revision.current = result.revision
        saved.current = sent
        report(JSON.stringify(latest.current) === sent ? '草稿已保存' : '有新修改，继续保存…')
      }
    }
    pending.current = run().catch(error => {
      report(`草稿保存失败：${error instanceof Error ? error.message : '请重试'}`)
      throw error
    }).finally(() => { pending.current = null })
    return pending.current
  }
  const flushRef = useRef(flush)
  flushRef.current = flush
  useEffect(() => {
    if (encoded === saved.current || closed.current || paused.current) return
    report('有修改，等待保存…')
    const timer = window.setTimeout(() => { if (!paused.current) void flushRef.current().catch(() => {}) }, 1000)
    return () => window.clearTimeout(timer)
  }, [encoded])
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!closed.current && JSON.stringify(latest.current) !== saved.current) { event.preventDefault(); event.returnValue = '' }
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [])
  return {
    status, flush, sourceId: source.current,
    pause: () => { paused.current = true },
    resume: () => { paused.current = false },
    finish: () => { closed.current = true },
    publish: async (asNew: boolean) => {
      await flush(true)
      const result = await api.publishDraft(id.current, revision.current, asNew)
      closed.current = true
      return result.question
    },
    discard: async () => {
      // Stop auto saves, wait for any in-flight write, then retire this stable ID.
      paused.current = true
      // Reconcile a possibly committed write whose response was lost before deleting.
      if (pending.current) await pending.current
      try {
        const remote = await api.draft(id.current)
        if (remote.revision !== revision.current) throw new Error('草稿版本已变化，请先保存重试或重新打开草稿箱')
        await api.discardDraft(id.current, revision.current)
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) throw error
      }
      closed.current = true
    },
  }
}
