/**
 * The leads table — the screen the founder actually lives in.
 *
 * Mobile-first, as required: below 780px each row becomes a card, because a
 * 12-column table on a phone is unusable and this founder will check leads on
 * a phone far more often than at a desk.
 *
 * Status is editable inline. Every date has already been converted to IST by
 * the backend; the frontend never formats a timestamp itself, which is how we
 * guarantee there is exactly one place time zones can go wrong.
 */

const LABEL_TONE = {
  'Immediate requirement': 'tone-now',
  'Planned requirement': 'tone-soon',
  'Exploring options': 'tone-later',
  'Details pending': 'tone-none',
}

export default function LeadTable({ leads = [], statuses = [], onOpen, onStatusChange }) {
  if (!leads.length) {
    return (
      <div className="empty-state">
        <h3>No enquiries yet</h3>
        <p>Open the site, have a chat with the assistant, and share an email — it will land here.</p>
      </div>
    )
  }

  return (
    <div className="lead-table">
      <div className="lead-head">
        <span>Who</span>
        <span>Wants</span>
        <span>Budget</span>
        <span>Timeline</span>
        <span>Status</span>
        <span>Arrived</span>
      </div>

      {leads.map((lead) => (
        <div className="lead-row" key={lead.id}>
          <div className="cell who" data-label="Who">
            <button type="button" className="link-name" onClick={() => onOpen(lead.id)}>
              {lead.name || 'Unnamed visitor'}
            </button>
            <div className="who-sub">
              {lead.email && <a href={`mailto:${lead.email}`}>{lead.email}</a>}
              {lead.phone && (
                <a href={lead.whatsapp_link} target="_blank" rel="noopener noreferrer">
                  +91 {lead.phone}
                </a>
              )}
              {!lead.email && !lead.phone && <span className="muted">no contact shared</span>}
            </div>
            {lead.category === 'careers' && <span className="tag tag-careers">careers</span>}
          </div>

          <div className="cell" data-label="Wants">
            {lead.requirement || <span className="muted">—</span>}
          </div>

          <div className="cell" data-label="Budget">
            {lead.budget || <span className="muted">—</span>}
          </div>

          <div className="cell" data-label="Timeline">
            <span className={`pill ${LABEL_TONE[lead.timeline_label] || ''}`}>
              {lead.timeline_label}
            </span>
            {lead.timeline_raw && <div className="raw-quote">“{lead.timeline_raw}”</div>}
          </div>

          <div className="cell" data-label="Status">
            <select
              value={lead.founder_status}
              onChange={(e) => onStatusChange(lead.id, e.target.value)}
              className={`status-select status-${lead.founder_status.replace(/\s+/g, '-').toLowerCase()}`}
            >
              {statuses.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <div className="cell muted small" data-label="Arrived">
            {lead.created_at}
          </div>
        </div>
      ))}
    </div>
  )
}
