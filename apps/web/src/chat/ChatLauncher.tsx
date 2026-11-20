import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { MessageCircle, RotateCcw, SendHorizontal, Sparkles } from 'lucide-react'
import { Badge, Button, Kbd, Sheet, SheetContent, Tooltip, toast } from '@/components/ui'
import { api, useApi } from '@/lib/api'
import { ROLE_LABELS, useRole } from '@/lib/role'
import { cn } from '@/lib/utils'
import { ChatMessage } from './ChatMessage'
import { DEMO_QUESTIONS, mockAnswer } from './mockChat'
import { draftBody, type ChatReplyData, type ChatTurn, type DraftAction, type Suggestion } from './types'

let seq = 0
const nextId = () => `t${Date.now().toString(36)}${(seq++).toString(36)}`

const reducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Floating AI assistant button + right-side chat panel (task C1). Mounted by the app shell. */
export function ChatLauncher() {
  const role = useRole()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [reveal, setReveal] = useState<{ id: string; chars: number } | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const sugg = useApi<{ suggestions: Suggestion[] }>(open && api.mode === 'live' ? '/api/chat/suggestions' : null)
  const suggestions: Suggestion[] = api.mode === 'live' && sugg.data?.suggestions?.length ? sugg.data.suggestions : DEMO_QUESTIONS

  // Streaming-like reveal of the latest assistant reply.
  useEffect(() => {
    if (!reveal) return
    const turn = turns.find((t) => t.id === reveal.id)
    if (!turn) return
    if (reveal.chars >= turn.content.length) {
      setTurns((ts) => ts.map((t) => (t.id === reveal.id ? { ...t, revealing: false } : t)))
      setReveal(null)
      return
    }
    const step = Math.max(2, Math.ceil(turn.content.length / 60))
    const timer = window.setTimeout(() => setReveal({ id: reveal.id, chars: reveal.chars + step }), 16)
    return () => window.clearTimeout(timer)
  }, [reveal, turns])

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [turns, reveal, busy])

  const send = useCallback(
    async (text: string) => {
      const message = text.trim()
      if (!message || busy) return
      const history = turns.slice(-8).map((t) => ({ role: t.role, content: t.content }))
      setTurns((ts) => [...ts, { id: nextId(), role: 'user', content: message }])
      setInput('')
      setBusy(true)
      let data: ChatReplyData
      let error = false
      try {
        data =
          api.mode === 'live'
            ? await api.post<ChatReplyData>('/api/chat', { message, history, role })
            : await mockAnswer(message, role)
      } catch (e) {
        error = true
        data = { reply: `Sorry, I could not answer that: ${(e as Error).message}`, actions: [], sources: [] }
      }
      const id = nextId()
      const animate = !reducedMotion() && !error
      setTurns((ts) => [
        ...ts,
        {
          id,
          role: 'assistant',
          content: data.reply ?? '',
          actions: Array.isArray(data.actions) ? data.actions : [],
          sources: Array.isArray(data.sources) ? data.sources : [],
          error,
          revealing: animate,
        },
      ])
      if (animate) setReveal({ id, chars: 0 })
      setBusy(false)
      inputRef.current?.focus()
    },
    [busy, turns, role],
  )

  const goTo = useCallback(
    (to: string) => {
      setOpen(false)
      navigate(to)
    },
    [navigate],
  )

  const setDraftState = (turnId: string, index: number, state: NonNullable<ChatTurn['drafts']>[number]) =>
    setTurns((ts) => ts.map((t) => (t.id === turnId ? { ...t, drafts: { ...t.drafts, [index]: state } } : t)))

  const onDraft = async (turnId: string, index: number, confirm: boolean) => {
    const turn = turns.find((t) => t.id === turnId)
    const draft = turn?.actions?.[index] as DraftAction | undefined
    if (!draft) return
    if (!confirm) {
      setDraftState(turnId, index, 'cancelled')
      return
    }
    setDraftState(turnId, index, 'saving')
    try {
      await api.post(draft.endpoint, draftBody(draft))
      setDraftState(turnId, index, 'confirmed')
      toast.success('Saved', { description: draft.summary })
    } catch (e) {
      setDraftState(turnId, index, 'pending')
      toast.error('Could not save', { description: (e as Error).message })
    }
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void send(input)
    }
  }

  const shownText = (t: ChatTurn) => (t.revealing && reveal?.id === t.id ? t.content.slice(0, reveal.chars) : t.revealing ? '' : t.content)

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <Tooltip content="Ask Pro Labels AI" side="left">
        <button
          type="button"
          aria-label="Open AI assistant"
          onClick={() => setOpen(true)}
          className={cn(
            'fixed right-6 bottom-6 z-40 flex size-14 items-center justify-center rounded-full bg-accent text-accent-foreground shadow-lg',
            'transition-[transform,background-color] duration-150 hover:-translate-y-0.5 hover:bg-accent-hover active:scale-95',
            'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
          )}
        >
          <MessageCircle className="size-6" strokeWidth={2} />
        </button>
      </Tooltip>
      <SheetContent
        side="right"
        className="max-w-lg"
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          inputRef.current?.focus()
        }}
        title={
          <span className="flex items-center gap-2">
            <Sparkles className="size-4 text-accent" aria-hidden /> Pro Labels AI
            <Badge tone="neutral">{ROLE_LABELS[role]}</Badge>
            {api.mode === 'mock' && <Badge tone="warn">Demo</Badge>}
          </span>
        }
        description="Ask in English or Hindi. I can read data and prepare drafts; nothing changes until you confirm."
        footer={
          <form
            className="flex w-full items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              void send(input)
            }}
          >
            {turns.length > 0 && (
              <Tooltip content="New chat">
                <Button type="button" variant="ghost" size="icon" aria-label="New chat" onClick={() => setTurns([])} disabled={busy}>
                  <RotateCcw />
                </Button>
              </Tooltip>
            )}
            <label className="sr-only" htmlFor="chat-input">
              Message
            </label>
            <textarea
              id="chat-input"
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Ask anything… e.g. Open JC-1301"
              className="max-h-32 min-h-11 flex-1 resize-none rounded-md border border-border bg-surface px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-ring"
            />
            <Button type="submit" size="icon" className="size-11" aria-label="Send" disabled={!input.trim()} loading={busy}>
              {!busy && <SendHorizontal />}
            </Button>
          </form>
        }
      >
        <div className="flex min-h-full flex-col gap-4" aria-live="polite">
          {turns.length === 0 && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Try one of these, or type your own. <Kbd>Enter</Kbd> sends, <Kbd>Esc</Kbd> closes.
              </p>
            </div>
          )}
          {turns.map((t) => (
            <ChatMessage key={t.id} turn={t} shownText={shownText(t)} onNavigate={goTo} onDraft={onDraft} />
          ))}
          {busy && (
            <div className="flex items-center gap-1.5 pl-10 text-muted-foreground" aria-label="Thinking">
              {[0, 1, 2].map((i) => (
                <span key={i} className="size-1.5 animate-pulse rounded-full bg-current" style={{ animationDelay: `${i * 150}ms` }} />
              ))}
            </div>
          )}
          {!busy && (
            <div className={cn('flex flex-wrap gap-2', turns.length > 0 && 'mt-auto pt-2')}>
              {(turns.length === 0 ? suggestions : suggestions.slice(0, 3)).map((s) => (
                <button
                  key={s.text}
                  type="button"
                  lang={s.lang}
                  onClick={() => void send(s.text)}
                  className="min-h-9 rounded-full border border-border bg-surface px-3 py-1.5 text-left text-sm text-foreground transition-[border-color,background-color,transform] duration-150 hover:border-accent hover:bg-accent-soft active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  {s.text}
                </button>
              ))}
            </div>
          )}
          <div ref={endRef} />
        </div>
      </SheetContent>
    </Sheet>
  )
}

export default ChatLauncher
