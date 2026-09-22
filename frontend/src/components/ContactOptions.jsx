/**
 * The "talk to the team" panel — feature (d).
 *
 * Three ways out, always the same three, always available: WhatsApp, book a
 * call, or leave an email. It appears automatically when the assistant does not
 * know something, when the visitor asks for a human, and when anything goes
 * wrong on our side.
 *
 * That last case is the important one: if the model is down or the daily cap is
 * spent, the visitor still gets a working route to Praxon instead of a dead end.
 */

export default function ContactOptions({ contacts = {}, compact = false }) {
  const { whatsapp, booking, email } = contacts
  if (!whatsapp && !booking && !email) return null

  return (
    <div className={`contact-options ${compact ? 'compact' : ''}`}>
      {!compact && <div className="contact-title">Talk to the team</div>}

      <div className="contact-buttons">
        {whatsapp && (
          <a className="contact-btn whatsapp" href={whatsapp} target="_blank" rel="noopener noreferrer">
            <span className="ico" aria-hidden="true">💬</span> WhatsApp
          </a>
        )}
        {booking && (
          <a className="contact-btn" href={booking} target="_blank" rel="noopener noreferrer">
            <span className="ico" aria-hidden="true">📅</span> Book a call
          </a>
        )}
        {email && (
          <a className="contact-btn" href={`mailto:${email}`}>
            <span className="ico" aria-hidden="true">✉️</span> Email
          </a>
        )}
      </div>
    </div>
  )
}
