import { useCallback, useEffect, useRef, useState } from 'react'
import BotAvatar from '../components/BotAvatar.jsx'
import ContactOptions from '../components/ContactOptions.jsx'
import MessageBubble from '../components/MessageBubble.jsx'
import QuickReplies from '../components/QuickReplies.jsx'
import { resetSession, skipLeadQuestion, streamChat, warmup } from '../api.js'

/**
 * The chat itself. This page is what loads inside the widget's iframe.
 *
 * Speed decisions visible here (section 6):
 *  - the typing indicator appears the instant Send is pressed, so there is
 *    never a moment of nothing happening
 *  - tokens are appended as they arrive; nothing waits for the full reply
 *  - warmup() fires on mount, waking Neon while the visitor reads the welcome
 *  - the composer stays enabled, so a visitor can type their next question
 *    while the current answer is still streaming
 */
export default function ChatWindow({ config }) {
  const chat = config.chat || {}
  const contacts = config.contacts || {}

  const [messages, setMessages] = useState([
    { role: 'assistant', content: chat.welcome_message || 'Hi! How can I help?' },
  ])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [chips, setChips] = useState([])
  const [leadField, setLeadField] = useState('')
  const [showContacts, setShowContacts] = useState(false)
  const [contactData, setContactData] = useState({})
  const [lastLatency, setLastLatency] = useState(null)

  const scrollRef = useRef(null)
  const inputRef = useRef(null)

  // Wake the database before the visitor has typed anything.
  useEffect(() => {
    warmup()
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, chips, showContacts])

  const send = useCallback(
    async (text) => {
      const message = (text ?? input).trim()
      if (!message || streaming) return

      setInput('')
      setChips([])
      setShowContacts(false)
      setLeadField('')
      setStreaming(true)

      setMessages((prev) => [
        ...prev,
        { role: 'user', content: message },
        { role: 'assistant', content: '', typing: true },
      ])

      const appendToLast = (updater) =>
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          next[next.length - 1] = { ...last, ...updater(last), typing: false }
          return next
        })

      await streamChat(message, {
        onMeta: (meta) => {
          if (meta.chips?.length) setChips(meta.chips)
          if (meta.lead_field) setLeadField(meta.lead_field)
          if (meta.contact_options) {
            setShowContacts(true)
            setContactData(meta.contacts || contacts)
          }
        },
        onToken: (t) => appendToLast((last) => ({ content: last.content + t })),
        onReplace: (t) => appendToLast(() => ({ content: t })),
        onDone: (info) => setLastLatency(info.latency_ms),
        onError: (msg) => {
          // Whatever went wrong, the visitor gets a sentence AND a route to a
          // human. A chat window that fails silently is worse than no chat.
          setShowContacts(true)
          setContactData(contacts)
          appendToLast((last) => ({
            content:
              last.content ||
              `${msg}. You can still reach the team directly — the buttons below work.`,
          }))
        },
      })

      setStreaming(false)
      inputRef.current?.focus()
    },
    [input, streaming, contacts],
  )

  const handleSkip = async () => {
    if (!leadField) return
    await skipLeadQuestion(leadField)
    setChips([])
    setLeadField('')
    setMessages((prev) => [
      ...prev,
      { role: 'assistant', content: "No problem — I won't ask again. What else can I help with?" },
    ])
  }

  const startOver = () => {
    resetSession()
    setMessages([{ role: 'assistant', content: chat.welcome_message || 'Hi! How can I help?' }])
    setChips([])
    setShowContacts(false)
    setLeadField('')
  }

  const showQuickQuestions = messages.length === 1 && !streaming

  return (
    <div className="chat-shell">
      <header className="chat-header">
        <div className="chat-header-main">
          <div className="chat-avatar" aria-hidden="true">
            <BotAvatar size={30} accent={config.branding?.accent_color} />
          </div>
          <div>
            <div className="chat-title">{chat.bot_name || 'Assistant'}</div>
            <div className="chat-sub">
              <span className="dot-online" /> {config.company?.name} · replies instantly
            </div>
          </div>
        </div>
        <button type="button" className="chat-reset" onClick={startOver} title="Start a new chat">
          ↻
        </button>
      </header>

      <div className="chat-body" ref={scrollRef}>
        {messages.map((m, i) => (
          <MessageBubble key={i} role={m.role} content={m.content} typing={m.typing} />
        ))}

        {showQuickQuestions && (
          <QuickReplies items={chat.quick_questions || []} onPick={(q) => send(q)} variant="quick" />
        )}

        {chips.length > 0 && (
          <QuickReplies
            items={chips}
            variant="lead"
            disabled={streaming}
            onPick={(c) => send(c)}
            onSkip={handleSkip}
          />
        )}

        {showContacts && <ContactOptions contacts={contactData} />}
      </div>

      <form
        className="chat-composer"
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
      >
        <input
          ref={inputRef}
          type="text"
          value={input}
          maxLength={chat.max_message_chars || 1200}
          placeholder={chat.placeholder || 'Type your question...'}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            // Explicit, rather than relying on the browser's implicit form
            // submit. Some mobile keyboards send Enter without submitting, and
            // "I typed my question and nothing happened" is a lost lead.
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
          aria-label="Your message"
        />
        <button type="submit" disabled={!input.trim() || streaming} aria-label="Send">
          {streaming ? <span className="mini-spinner" /> : '↑'}
        </button>
      </form>

      <div className="chat-foot">
        AI assistant · answers from {config.company?.name}&apos;s own content
        {lastLatency ? <span className="latency"> · {lastLatency} ms</span> : null}
      </div>
    </div>
  )
}
