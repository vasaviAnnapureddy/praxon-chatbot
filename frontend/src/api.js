/**
 * Every call to the backend goes through this file.
 *
 * Note what is NOT here: no base URL, no VITE_API_URL, no environment switch.
 * Every path is relative ("/api/chat"). In development Vite proxies those to
 * :8000; in production FastAPI serves the React build itself, so the frontend
 * and the API are the same origin. The identical build therefore works on
 * localhost, on the Render URL, and on praxontech.in later, with no rebuild.
 *
 * That was a deployment requirement in section 8, and getting it wrong is the
 * classic reason a demo works locally and breaks live.
 */

const SESSION_KEY = 'praxon_session_id'

/** A stable id per browser so a reload does not start a new conversation. */
export function getSessionId() {
  try {
    let id = localStorage.getItem(SESSION_KEY)
    if (!id) {
      id = 'sess_' + Math.random().toString(36).slice(2) + Date.now().toString(36)
      localStorage.setItem(SESSION_KEY, id)
    }
    return id
  } catch {
    // Private browsing with storage blocked: fall back to a per-page id.
    return 'sess_' + Math.random().toString(36).slice(2) + Date.now().toString(36)
  }
}

export function resetSession() {
  try {
    localStorage.removeItem(SESSION_KEY)
  } catch {
    /* ignore */
  }
  return getSessionId()
}

export async function getConfig() {
  const res = await fetch('/api/config')
  if (!res.ok) throw new Error('Could not load site configuration')
  return res.json()
}

/** Fired when the bubble is opened, so Neon is awake before they type. */
export function warmup() {
  return fetch('/api/warmup', { method: 'POST' }).catch(() => {})
}

export function skipLeadQuestion(field) {
  return fetch('/api/skip', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: getSessionId(), message: field }),
  }).catch(() => {})
}

/**
 * Streams a reply.
 *
 * EventSource cannot be used here because it only does GET and we need to POST
 * the message, so this reads the SSE stream out of fetch() by hand.
 *
 * Callbacks:
 *   onMeta({intent, chips, lead_field, contact_options, contacts})  - before any text
 *   onToken(text)     - append this to the visible reply
 *   onReplace(text)   - the guard rewrote the answer; replace what is on screen
 *   onDone({latency_ms, total_ms})
 *   onError(message)
 */
export async function streamChat(message, handlers = {}) {
  const { onMeta, onToken, onReplace, onDone, onError } = handlers
  const controller = new AbortController()

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: getSessionId(), message }),
      signal: controller.signal,
    })

    if (!res.ok || !res.body) {
      throw new Error(`Server returned ${res.status}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // SSE frames are separated by a blank line.
      const frames = buffer.split('\n\n')
      buffer = frames.pop() || ''

      for (const frame of frames) {
        let event = 'message'
        let data = ''
        for (const line of frame.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) data += line.slice(5).trim()
        }
        if (!data) continue

        let parsed
        try {
          parsed = JSON.parse(data)
        } catch {
          continue
        }

        if (event === 'meta') onMeta?.(parsed)
        else if (event === 'token') onToken?.(parsed.t || '')
        else if (event === 'replace') onReplace?.(parsed.t || '')
        else if (event === 'done') onDone?.(parsed)
        else if (event === 'error') onError?.(parsed.detail || 'Something went wrong')
      }
    }
  } catch (err) {
    onError?.(err.message || 'Connection lost')
  }

  return () => controller.abort()
}

/* ------------------------------------------------------------------ login */
/*
 * ONE sign-in page (/login). The server says who you are; your ROLE decides
 * where you go: owner/team -> /admin, client -> /portal.
 *
 * The pass is still kept under one of two keys, by role, so a team member
 * testing the client portal in the same browser isn't logged out of the dashboard:
 *    owner, team -> praxon_admin_token
 *    client      -> praxon_client_token
 *    (first sign-in with a temporary password -> praxon_setup_token, which only
 *     opens the "choose your own password" step)
 * The SERVER still checks every pass's role on every request — these keys only
 * keep the logins apart in the browser.
 */
const TOKEN_KEYS = { team: 'praxon_admin_token', client: 'praxon_client_token', setup: 'praxon_setup_token' }
const doorFor = (role) => (role === 'client' ? 'client' : 'team')

function readToken(door) {
  try {
    return localStorage.getItem(TOKEN_KEYS[door]) || ''
  } catch {
    return ''
  }
}

function writeToken(door, token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEYS[door], token)
    else localStorage.removeItem(TOKEN_KEYS[door])
  } catch {
    /* private browsing can block storage — the login just won't persist */
  }
}

export const getToken = () => readToken('team')
export const setToken = (t) => writeToken('team', t)
export const getClientToken = () => readToken('client')

async function authedFetch(door, path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${readToken(door)}`,
      ...(options.headers || {}),
    },
  })
  if (res.status === 401) {
    writeToken(door, '')
    throw new Error('Session expired — please sign in again')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed (${res.status})`)
  }
  return res.json()
}

const adminFetch = (path, options) => authedFetch('team', path, options)
const portalFetch = (path, options) => authedFetch('client', path, options)

async function post(path, data, headers = {}) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(data),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || 'Something went wrong')
  return body
}

/** Saves the normal pass under the right key and says where to go. */
function signedIn(body) {
  writeToken('setup', '')
  writeToken(doorFor(body.user.role), body.token)
  return { user: body.user, home: body.home }
}

export const auth = {
  /**
   * `how` is {login, password} or {credential} (Google). Returns either
   *   { home: '/admin' | '/portal', user }       -> signed in, go there
   *   { mustChangePassword: true, user }         -> temporary password: choose your own first
   */
  async signIn(how) {
    const body = await post(how.credential ? '/api/auth/google' : '/api/auth/login', how)
    if (body.must_change_password) {
      writeToken('setup', body.token)
      return { mustChangePassword: true, user: body.user }
    }
    return signedIn(body)
  },

  /** Step 2 of a first sign-in: swaps the setup pass for a normal one. */
  async choosePassword(newPassword) {
    const body = await post(
      '/api/auth/password',
      { new: newPassword },
      { Authorization: `Bearer ${readToken('setup')}` },
    )
    return signedIn(body)
  },

  requestAccess: (data) => post('/api/auth/request-access', data),
}

export const admin = {
  logout: () => writeToken('team', ''),

  me: () => adminFetch('/api/admin/me'),

  // --- people -------------------------------------------------------------
  team: () => adminFetch('/api/admin/team'),
  addTeamMember: (data) => adminFetch('/api/admin/team', { method: 'POST', body: JSON.stringify(data) }),
  clients: () => adminFetch('/api/admin/clients'),
  addClient: (data) => adminFetch('/api/admin/clients', { method: 'POST', body: JSON.stringify(data) }),
  changeUser: (id, data) =>
    adminFetch(`/api/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  /** New temporary password + emailed to them. Their old password stops working. */
  sendSignIn: (id) =>
    adminFetch(`/api/admin/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ reset_password: true, send_email: true }),
    }),

  // --- access requests ----------------------------------------------------
  requests: () => adminFetch('/api/admin/requests'),
  changeRequest: (id, data) =>
    adminFetch(`/api/admin/requests/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  approveRequest: (id) =>
    adminFetch(`/api/admin/requests/${id}/approve`, { method: 'POST', body: JSON.stringify({ send_email: true }) }),
  rejectRequest: (id) => adminFetch(`/api/admin/requests/${id}/reject`, { method: 'POST' }),

  // --- projects -----------------------------------------------------------
  projects: () => adminFetch('/api/admin/projects'),
  project: (id) => adminFetch(`/api/admin/projects/${id}`),
  createProject: (data) =>
    adminFetch('/api/admin/projects', { method: 'POST', body: JSON.stringify(data) }),
  changeProject: (id, data) =>
    adminFetch(`/api/admin/projects/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteProject: (id) => adminFetch(`/api/admin/projects/${id}`, { method: 'DELETE' }),
  postUpdate: (id, data) =>
    adminFetch(`/api/admin/projects/${id}/updates`, { method: 'POST', body: JSON.stringify(data) }),
  stats: () => adminFetch('/api/admin/stats'),
  leads: (params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== '' && v != null),
    ).toString()
    return adminFetch(`/api/admin/leads${qs ? `?${qs}` : ''}`)
  },
  lead: (id) => adminFetch(`/api/admin/leads/${id}`),
  setStatus: (id, status, notes) =>
    adminFetch(`/api/admin/leads/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status, notes }),
    }),
  deleteLead: (id) => adminFetch(`/api/admin/leads/${id}`, { method: 'DELETE' }),
  conversations: () => adminFetch('/api/admin/conversations'),
  conversation: (id) => adminFetch(`/api/admin/conversations/${id}`),
  unanswered: () => adminFetch('/api/admin/unanswered'),
  resolveUnanswered: (id) =>
    adminFetch(`/api/admin/unanswered/${id}/resolve`, { method: 'POST' }),
  testEmail: () => adminFetch('/api/admin/test-email', { method: 'POST' }),

  /** CSV needs the token in a header, so it is fetched then saved as a blob. */
  async downloadCsv() {
    const res = await fetch('/api/admin/leads.csv', {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    if (!res.ok) throw new Error('Export failed')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `praxon-leads-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  },
}

/* ----------------------------------------------------------------- portal */
/* Praxon's CUSTOMERS. The server only ever returns their own projects. */
export const portal = {
  logout: () => writeToken('client', ''),
  me: () => portalFetch('/api/auth/me'),
  projects: () => portalFetch('/api/portal/projects'),
  project: (id) => portalFetch(`/api/portal/projects/${id}`),
  reply: (id, body) =>
    portalFetch(`/api/portal/projects/${id}/messages`, { method: 'POST', body: JSON.stringify({ body }) }),
}
