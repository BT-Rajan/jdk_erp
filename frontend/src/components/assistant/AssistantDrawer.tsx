import { useEffect, useRef, useState } from 'react'
import { Send } from 'lucide-react'
import { Drawer } from '@/components/ui/Drawer'
import { ApiError, apiClient } from '@/lib/apiClient'
import { cn } from '@/lib/cn'
import { renderMarkdownLite } from '@/lib/markdownLite'

export interface AssistantMessage {
  role: 'user' | 'assistant'
  content: string
}

interface AssistantDrawerProps {
  open: boolean
  onClose: () => void
}

const GREETING: AssistantMessage = {
  role: 'assistant',
  content:
    "Hi! I'm the JDK Assistant. Ask me how to do something in JDK ERP, or the status of a quotation, order, RFQ, purchase order, receipt, payment or stock item. I only answer questions -- I can't make changes.",
}

// Mirrors the server's own cap (assistant_service.MAX_HISTORY).
const HISTORY_LIMIT = 10

/** The JDK Assistant chat (backend/app/api/assistant.py), adapted from
 * jdk_clean. Read-only: it answers questions; the server refuses to do
 * anything else. The greeting is local and never sent as history. */
export function AssistantDrawer({ open, onClose }: AssistantDrawerProps) {
  const [messages, setMessages] = useState<AssistantMessage[]>([GREETING])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo?.({ top: scrollRef.current.scrollHeight })
  }, [messages, sending])

  async function send() {
    const message = input.trim()
    if (!message || sending) return
    const history = messages.slice(1).slice(-HISTORY_LIMIT)
    const next: AssistantMessage[] = [...messages, { role: 'user', content: message }]
    setMessages(next)
    setInput('')
    setError(null)
    setSending(true)
    try {
      const { data } = await apiClient.post<{ reply: string }>('/api/assistant/chat', { message, history })
      setMessages([...next, { role: 'assistant', content: data.reply }])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The assistant could not be reached. Please try again.')
    } finally {
      setSending(false)
      inputRef.current?.focus()
    }
  }

  return (
    <Drawer
      open={open}
      title="JDK Assistant"
      onClose={onClose}
      initialFocusRef={inputRef}
      footer={
        <div className="flex w-full items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
            rows={2}
            maxLength={2000}
            aria-label="Ask the assistant"
            placeholder="Ask a question..."
            className="flex-1 resize-none rounded-md border border-ink-600 bg-ink-950 px-3 py-2 text-sm text-gold-100 placeholder:text-gold-100/40 focus:border-gold-400 focus:outline-none"
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={sending || !input.trim()}
            aria-label="Send"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-gold-500/20 text-gold-200 transition-colors hover:bg-gold-500/30 disabled:opacity-40"
          >
            <Send size={16} />
          </button>
        </div>
      }
    >
      <div ref={scrollRef} className="space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
            <div
              className={cn(
                'max-w-[85%] rounded-lg px-3 py-2 text-sm',
                m.role === 'user' ? 'bg-gold-500/15 text-gold-100' : 'bg-ink-800 text-gold-100/85',
              )}
            >
              {renderMarkdownLite(m.content)}
            </div>
          </div>
        ))}
        {sending && <div className="text-sm text-gold-100/50">Thinking...</div>}
        {error && <p className="text-sm text-danger-500">{error}</p>}
      </div>
    </Drawer>
  )
}
