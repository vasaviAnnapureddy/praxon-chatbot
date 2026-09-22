import { useState } from 'react'

/**
 * One enquiry, with the whole conversation that produced it.
 *
 * The transcript is the point. A summary can be wrong; the actual words the
 * visitor typed cannot. The founder reads what was said and decides what to do.
 *
 * Delete is here too, and it removes the conversation as well as the row —
 * a privacy request means the transcript goes, not just the summary of it.
 */
export default function LeadDetail({ data, statuses = [], onClose, onStatusChange, onDelete }) {
  const [notes, setNotes] = useState(data.lead.founder_notes || '')
  const [saving, setSaving] = useState(false)
  const [confirming, setConfirming] = useState(false)

  const lead = data.lead

  const saveNotes = async () => {
    setSaving(true)
    await onStatusChange(lead.id, lead.founder_status, notes)
    setSaving(false)
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <div>
            <h2>{lead.name || 'Unnamed visitor'}</h2>
            <div className="drawer-sub">{lead.created_at}</div>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>

        <div className="drawer-body">
          <section className="facts">
            <Fact label="Email" value={lead.email} link={lead.email ? `mailto:${lead.email}` : ''} />
            <Fact
              label="Phone"
              value={lead.phone ? `+91 ${lead.phone}` : ''}
              link={lead.whatsapp_link}
            />
            <Fact label="Company" value={lead.company_name} />
            <Fact label="Wants" value={lead.requirement} />
            <Fact label="Budget said" value={lead.budget} />
            <Fact label="Timeline said" value={lead.timeline_raw} />
            <Fact label="Timeline label" value={`${lead.timeline_label} — ${lead.timeline_note}`} />
            <Fact label="Category" value={lead.category} />
            <Fact label="Alert emailed" value={lead.alert_sent ? 'Yes' : 'Not sent'} />
          </section>

          <section className="drawer-actions">
            <label>
              Status
              <select
                value={lead.founder_status}
                onChange={(e) => onStatusChange(lead.id, e.target.value, notes)}
              >
                {statuses.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>

            <label className="notes-label">
              Your notes
              <textarea
                rows={3}
                value={notes}
                placeholder="Called on Tuesday, sending a proposal..."
                onChange={(e) => setNotes(e.target.value)}
              />
            </label>

            <div className="drawer-btn-row">
              <button type="button" className="btn" onClick={saveNotes} disabled={saving}>
                {saving ? 'Saving...' : 'Save notes'}
              </button>

              {lead.phone && (
                <a
                  className="btn btn-whatsapp"
                  href={lead.whatsapp_link}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  WhatsApp
                </a>
              )}
              {lead.email && (
                <a className="btn btn-ghost" href={`mailto:${lead.email}`}>
                  Email
                </a>
              )}
            </div>
          </section>

          <section className="transcript">
            <h3>Full conversation</h3>
            {data.messages.map((m) => (
              <div key={m.id} className={`t-msg ${m.role}`}>
                <div className="t-who">
                  {m.role === 'user' ? 'Visitor' : 'Assistant'}
                  <span className="t-time">{m.created_at}</span>
                  {m.blocked_reason && <span className="t-flag">{m.blocked_reason}</span>}
                </div>
                <div className="t-text">{m.content}</div>
              </div>
            ))}
          </section>

          <section className="danger-zone">
            {!confirming ? (
              <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
                Delete this enquiry
              </button>
            ) : (
              <div className="confirm">
                <p>
                  This permanently deletes the enquiry <strong>and the full conversation</strong>.
                  It cannot be undone.
                </p>
                <div className="drawer-btn-row">
                  <button type="button" className="btn btn-danger" onClick={() => onDelete(lead.id)}>
                    Yes, delete permanently
                  </button>
                  <button type="button" className="btn btn-ghost" onClick={() => setConfirming(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </section>
        </div>
      </aside>
    </div>
  )
}

function Fact({ label, value, link }) {
  return (
    <div className="fact">
      <span className="fact-label">{label}</span>
      <span className="fact-value">
        {value ? (
          link ? (
            <a href={link} target="_blank" rel="noopener noreferrer">
              {value}
            </a>
          ) : (
            value
          )
        ) : (
          <span className="muted">not shared</span>
        )}
      </span>
    </div>
  )
}
