import { useEffect, useRef, useState } from 'react'

/**
 * Google's official "Continue with Google" button.
 *
 *   <GoogleButton clientId={config.auth.google_client_id} onCredential={fn} />
 *
 * How it works:
 *   1. load Google's small script once (accounts.google.com/gsi/client)
 *   2. Google draws its own button into our <div>
 *   3. the visitor picks their account in Google's popup
 *   4. Google hands us a signed "credential" -> onCredential(credential)
 *   5. we send it to /api/auth/google, and the SERVER checks Google's signature
 *
 *   Q: Why draw Google's button instead of our own styled one?
 *   A: Google's rules require their button for this sign-in, and people trust
 *      the button they recognise.
 *
 *   Q: What if the server has no GOOGLE_CLIENT_ID?
 *   A: clientId is "" and this renders nothing. Password login still works.
 */
const SCRIPT_SRC = 'https://accounts.google.com/gsi/client'
let scriptPromise = null            // shared, so the script loads once per page

function loadScript() {
  if (window.google?.accounts?.id) return Promise.resolve()
  if (!scriptPromise) {
    scriptPromise = new Promise((resolve, reject) => {
      const tag = document.createElement('script')
      tag.src = SCRIPT_SRC
      tag.async = true
      tag.onload = resolve
      tag.onerror = () => {
        scriptPromise = null        // allow a retry on the next render
        reject(new Error('Could not load Google sign-in'))
      }
      document.head.appendChild(tag)
    })
  }
  return scriptPromise
}

export default function GoogleButton({ clientId, onCredential, text = 'continue_with' }) {
  const box = useRef(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!clientId) return
    let alive = true
    loadScript()
      .then(() => {
        if (!alive || !box.current) return
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (response) => onCredential(response.credential),
        })
        window.google.accounts.id.renderButton(box.current, {
          theme: 'outline',
          size: 'large',
          shape: 'pill',
          text,                                       // "Continue with Google"
          width: Math.min(box.current.offsetWidth || 320, 400),
        })
      })
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [clientId, onCredential, text])

  if (!clientId) return null
  if (failed) return <p className="login-note">Google sign-in couldn't load. Use your password below.</p>

  return (
    <>
      <div ref={box} className="google-btn" />
      <div className="login-divider">
        <span>or</span>
      </div>
    </>
  )
}
