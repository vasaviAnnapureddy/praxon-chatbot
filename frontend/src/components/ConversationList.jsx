import { useState } from 'react'
import { admin } from '../api.js'

/**
 * Every conversation, not only the ones that became enquiries.
 *
 * This matters more than it looks. The chats where nobody shared an email are
 * where you find out that three people asked about Shopify work, or that the
 * assistant kept missing a question. A dashboard that only shows converted
 * leads hides all of that.
 */
export default function ConversationList({ conversations = [] }) {
  const [openId, setOpenId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(false)

  const open = async (id) => {
    if (openId === id) {
      setOpenId(null)
      setDetail(null)
      return
    }
    setOpenId(id)
    setLoading(true)
    try {
      setDetail(await admin.conversation(id))
    } catch {
      setDetail(null)
    } finally {
      setLoading(false)
    }
  }

  if (!conversations.length) {
    return (
      <div className="empty-state">
        <h3>No conversations yet</h3>
        <p>Every chat on the site appears here, whether or not it became an enquiry.</p>
      </div>
    )
  }

  return (
    <div className="conv-list">
      {conversations.map((c) => (
        <div className="conv-item" key={c.id}>
          <button type="button" className="conv-head" onClick={() => open(c.id)}>
            <span className="conv-id">#{c.id}</span>
            <span className="conv-meta">
              {c.message_count} messages · {c.language}
              {(c.intents || []).length > 0 && (
                <span className="conv-intents">
                  {c.intents.slice(0, 3).map((i) => (
                    <span className="tag" key={i}>
                      {i}
                    </span>
                  ))}
                </span>
              )}
            </span>
            <span className="conv-time">{c.last_active_at}</span>
            <span className="conv-caret">{openId === c.id ? '▾' : '▸'}</span>
          </button>

          {openId === c.id && (
            <div className="conv-body">
              {loading && <div className="muted">Loading...</div>}
              {detail?.lead && (
                <div className="conv-lead-note">
                  Enquiry attached: {detail.lead.name || 'unnamed'} ·{' '}
                  {detail.lead.timeline_label}
                </div>
              )}
              {detail?.messages?.map((m) => (
                <div key={m.id} className={`t-msg ${m.role}`}>
                  <div className="t-who">
                    {m.role === 'user' ? 'Visitor' : 'Assistant'}
                    <span className="t-time">{m.created_at}</span>
                    {m.latency_ms > 0 && <span className="t-lat">{m.latency_ms} ms</span>}
                  </div>
                  <div className="t-text">{m.content}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
