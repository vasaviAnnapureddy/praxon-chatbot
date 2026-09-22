import { useState } from 'react'

/**
 * The result of adding someone, approving them, or sending new sign-in details.
 *
 *   Emailed     -> a green line "Emailed to ...". Nothing else to do.
 *   Not emailed -> the reason, plus the password and a ready message to copy
 *                  into WhatsApp. (Resend's free plan only emails YOUR address
 *                  until a domain is verified — this is the fallback for that.)
 *
 * The temporary password is shown only here, only now: the server keeps just a
 * scrambled copy. If it's lost, "Send new sign-in details" makes a fresh one.
 */
export default function TempPassword({ info, onClose }) {
  const [copied, setCopied] = useState('')
  const [show, setShow] = useState(false)       // after a successful email, the copy part is folded away
  if (!info) return null

  const message =
    `Hi ${info.name || ''}, your ${info.company} account is ready.\n` +
    `Sign in at: ${window.location.origin}/login\n` +
    `Email: ${info.email}\n` +
    `Temporary password: ${info.password}\n` +
    `You'll choose your own password when you first sign in. This one expires in 7 days.`

  const copy = async (text, what) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(what)
    } catch {
      setCopied('')          // clipboard blocked: they can still select and copy by hand
    }
  }

  const copyPart = (
    <>
      <div className="temp-row">
        <code>{info.password}</code>
        <button type="button" className="btn btn-ghost small" onClick={() => copy(info.password, 'password')}>
          {copied === 'password' ? 'Copied' : 'Copy password'}
        </button>
      </div>
      <pre className="temp-message">{message}</pre>
      <button type="button" className="btn btn-ghost small" onClick={() => copy(message, 'message')}>
        {copied === 'message' ? 'Copied' : 'Copy message'}
      </button>
    </>
  )

  return (
    <div className={`panel temp-password ${info.emailSent ? 'sent' : ''}`}>
      <h3>{info.title}</h3>

      {info.emailSent ? (
        <p className="email-status ok">✓ {info.emailDetail}. They'll choose their own password when they sign in.</p>
      ) : (
        <>
          {info.emailDetail && <p className="email-status warn">{info.emailDetail}</p>}
          <p className="panel-note">
            Send this to <b>{info.name || info.email}</b> privately (WhatsApp or in person). It is shown only now.
          </p>
        </>
      )}

      {info.emailSent ? (
        show ? copyPart : (
          <button type="button" className="link-btn" onClick={() => setShow(true)}>
            Show the password anyway
          </button>
        )
      ) : (
        copyPart
      )}

      <div className="row-actions">
        <button type="button" className="btn btn-primary small" onClick={onClose}>
          Done
        </button>
      </div>
    </div>
  )
}

/** Turns the server's reply (user + email result) into what the box above needs. */
export function tempInfo(reply, company, title) {
  const user = reply?.user
  return user?.temp_password
    ? {
        title,
        company,
        name: user.name,
        email: user.email,
        password: user.temp_password,
        emailSent: Boolean(reply.email_sent),
        emailDetail: reply.email_detail || '',
      }
    : null
}
