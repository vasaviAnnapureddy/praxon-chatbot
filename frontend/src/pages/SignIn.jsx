import { useCallback, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import GoogleButton from '../components/GoogleButton.jsx'
import Logo from '../components/Logo.jsx'
import { auth } from '../api.js'

/**
 * The ONE sign-in page, at /login — owner, team and clients all come here.
 * After sign-in the server says the role, and the role decides where you go:
 *     owner / team -> /admin (dashboard)      client -> /portal
 *
 * Two steps:
 *   1. "signin"   Google, or username/email + password
 *   2. "choose"   only after a TEMPORARY password: choose your own. Nothing else
 *                 opens until this is done (the server enforces that too).
 *
 * No sign-up here. New people are added by the team; clients without an
 * account use "Request access".
 */
export default function SignIn({ config }) {
  const [step, setStep] = useState('signin')
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [next, setNext] = useState({ one: '', two: '' })   // the new password, twice
  const [who, setWho] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const company = config.company?.name

  const run = useCallback(
    async (attempt) => {
      setError('')
      setBusy(true)
      try {
        const result = await attempt()
        if (result.mustChangePassword) {
          setWho(result.user)
          setPassword('')
          setStep('choose')
        } else {
          navigate(result.home, { replace: true })
        }
      } catch (err) {
        setError(err.message || 'Sign in failed')
      } finally {
        setBusy(false)
      }
    },
    [navigate],
  )

  // useCallback so the Google button isn't redrawn on every keystroke.
  const onGoogle = useCallback((credential) => run(() => auth.signIn({ credential })), [run])

  if (step === 'choose') {
    return (
      <div className="login-page">
        <form
          className="login-card"
          onSubmit={(e) => {
            e.preventDefault()
            if (next.one !== next.two) return setError('The two passwords are not the same.')
            run(() => auth.choosePassword(next.one))
          }}
        >
          <Logo config={config} kind="full" className="login-logo" />
          <h1>Choose your password</h1>
          <p className="login-sub">
            Welcome{who?.name ? `, ${who.name}` : ''}. You signed in with a temporary password. Choose
            your own now — the temporary one stops working as soon as you do.
          </p>

          <label>
            New password
            <input
              type="password"
              value={next.one}
              onChange={(e) => setNext({ ...next, one: e.target.value })}
              autoComplete="new-password"
              autoFocus
              required
            />
          </label>
          <label>
            Type it again
            <input
              type="password"
              value={next.two}
              onChange={(e) => setNext({ ...next, two: e.target.value })}
              autoComplete="new-password"
              required
            />
          </label>
          <p className="login-note">At least 12 characters, with 3 of: lowercase, UPPERCASE, numbers, symbols.</p>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" className="btn btn-primary full" disabled={busy}>
            {busy ? 'Saving...' : 'Save and continue'}
          </button>
        </form>
      </div>
    )
  }

  return (
    <div className="login-page">
      <form
        className="login-card"
        onSubmit={(e) => {
          e.preventDefault()
          run(() => auth.signIn({ login: login.trim(), password }))
        }}
      >
        <Logo config={config} kind="full" className="login-logo" />
        <h1>Sign in</h1>
        <p className="login-sub">For the {company} team and our clients.</p>

        <GoogleButton clientId={config.auth?.google_client_id} onCredential={onGoogle} />

        <label>
          Email or username
          <input
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {error && <div className="login-error">{error}</div>}

        <button type="submit" className="btn btn-primary full" disabled={busy}>
          {busy ? 'Signing in...' : 'Sign in'}
        </button>

        <p className="login-foot">
          A client without an account? <Link to="/request-access">Request access</Link>
          <br />
          Forgot your password? Ask the person at {company} who added you.
          <br />
          <Link to="/">← Back to the website</Link>
        </p>
      </form>
    </div>
  )
}
