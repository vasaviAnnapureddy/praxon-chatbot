import { useState } from 'react'
import { Link } from 'react-router-dom'
import Logo from '../components/Logo.jsx'
import { auth } from '../api.js'

/**
 * "Request access", at /request-access — for CLIENTS who have no login yet.
 *
 * This does NOT create an account. It sends a request to the team's dashboard
 * (Requests tab) and emails the owner. A person approves or rejects it.
 * Team members never come through here: only the owner adds them.
 */
const EMPTY = { name: '', email: '', company_name: '', message: '', website: '' }

export default function RequestAccess({ config }) {
  const [form, setForm] = useState(EMPTY)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const company = config.company?.name
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await auth.requestAccess(form)
      setSent(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (sent) {
    return (
      <div className="login-page">
        <div className="login-card">
          <Logo config={config} kind="full" className="login-logo" />
          <h1>Request received</h1>
          <p className="login-sub">
            Thank you. The {company} team will check your request and contact you with your
            sign-in details.
          </p>
          <p className="login-foot">
            <Link to="/">← Back to the website</Link>
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <Logo config={config} kind="full" className="login-logo" />
        <h1>Request access</h1>
        <p className="login-sub">
          For {company} clients who want to follow their project online. The team reviews every request.
        </p>

        <label>
          Your name
          <input value={form.name} onChange={set('name')} autoComplete="name" autoFocus required />
        </label>
        <label>
          Email
          <input type="email" value={form.email} onChange={set('email')} autoComplete="email" required />
        </label>
        <label>
          Company <span className="muted">(optional)</span>
          <input value={form.company_name} onChange={set('company_name')} autoComplete="organization" />
        </label>
        <label>
          Message <span className="muted">(optional — e.g. which project)</span>
          <textarea rows={3} value={form.message} onChange={set('message')} />
        </label>
        {/* Spam trap: hidden from people, so only bots fill it. See auth.py. */}
        <input
          className="trap"
          tabIndex={-1}
          autoComplete="off"
          aria-hidden="true"
          value={form.website}
          onChange={set('website')}
        />

        {error && <div className="login-error">{error}</div>}

        <button type="submit" className="btn btn-primary full" disabled={busy}>
          {busy ? 'Sending...' : 'Send request'}
        </button>

        <p className="login-foot">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </div>
  )
}
