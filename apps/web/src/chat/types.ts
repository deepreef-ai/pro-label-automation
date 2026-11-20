import type { ChatSource } from '@contract/types'

export type { ChatSource }

export interface NavigateAction {
  type: 'navigate'
  to: string
}

/** Draft from a chat draft tool. The backend sends both `body` and `payload` (same object). */
export interface DraftAction {
  type: 'draft'
  entity?: string
  endpoint: string
  body?: Record<string, unknown>
  payload?: Record<string, unknown>
  summary: string
  /** Optional ready-to-send message text (e.g. a reminder). */
  text?: string
}

export type ChatAction = NavigateAction | DraftAction

export interface ChatReplyData {
  reply: string
  actions: ChatAction[]
  sources: ChatSource[]
}

export type DraftState = 'pending' | 'saving' | 'confirmed' | 'cancelled'

export interface ChatTurn {
  id: string
  role: 'user' | 'assistant'
  content: string
  actions?: ChatAction[]
  sources?: ChatSource[]
  drafts?: Record<number, DraftState>
  error?: boolean
  /** Assistant text still being revealed. */
  revealing?: boolean
}

export interface Suggestion {
  text: string
  lang: 'en' | 'hi'
}

export function draftBody(d: DraftAction): Record<string, unknown> {
  return d.body ?? d.payload ?? {}
}
