import { Suspense, lazy, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { getClientToken, getConfig, getToken } from './api.js'

/**
 * The routes, one app:
 *
 *   /                the Praxon demo website (with the widget installed)
 *   /chat            the chat window — this is what loads INSIDE the iframe
 *   /login           ONE sign-in for everybody; the role decides where you land
 *   /request-access  clients without an account ask for one
 *   /admin           dashboard (owner + team)
 *   /portal          client portal: their own projects
 *   (old links /admin/login and /portal/login still work — they go to /login)
 *
 * The dashboard is lazy-loaded: a visitor on their phone should never download
 * the leads table just to read the homepage.
 */

const DemoSite = lazy(() => import('./pages/DemoSite.jsx'))
const ChatWindow = lazy(() => import('./pages/ChatWindow.jsx'))
const SignIn = lazy(() => import('./pages/SignIn.jsx'))
const RequestAccess = lazy(() => import('./pages/RequestAccess.jsx'))
const AdminDashboard = lazy(() => import('./pages/AdminDashboard.jsx'))
const PortalHome = lazy(() => import('./pages/PortalHome.jsx'))

/** Turns company.yaml colours into CSS variables the whole app reads. */
function applyBranding(branding = {}) {
  const root = document.documentElement
  const map = {
    '--brand': branding.primary_color,
    '--brand-dark': branding.primary_dark,
    '--accent': branding.accent_color,
    '--text': branding.text_color,
    '--muted': branding.muted_color,
    '--surface': branding.surface_color,
    '--bg': branding.background_color,
    '--font': branding.font_stack,
  }
  for (const [key, value] of Object.entries(map)) {
    if (value) root.style.setProperty(key, value)
  }
  // The browser-tab icon, from company.yaml -> branding.favicon_url.
  if (branding.favicon_url) {
    let icon = document.querySelector("link[rel='icon']")
    if (!icon) {
      icon = document.createElement('link')
      icon.rel = 'icon'
      document.head.appendChild(icon)
    }
    icon.href = branding.favicon_url
  }
}

function Loading() {
  return (
    <div className="app-loading">
      <div className="spinner" />
    </div>
  )
}

function RequireAdmin({ children }) {
  return getToken() ? children : <Navigate to="/login" replace />
}

// Only checks a client pass EXISTS — the server checks it is real and a client's.
function RequireClient({ children }) {
  return getClientToken() ? children : <Navigate to="/login" replace />
}

export default function App() {
  const [config, setConfig] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    getConfig()
      .then((cfg) => {
        if (!alive) return
        applyBranding(cfg.branding)
        setConfig(cfg)
        if (cfg?.company?.name) document.title = cfg.company.name
      })
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [])

  if (failed) {
    return (
      <div className="app-loading">
        <div className="load-error">
          <h2>Can&apos;t reach the server</h2>
          <p>Start the backend, then reload this page.</p>
          <code>uvicorn app.main:app --reload --app-dir backend</code>
        </div>
      </div>
    )
  }

  if (!config) return <Loading />

  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/" element={<DemoSite config={config} />} />
        <Route path="/chat" element={<ChatWindow config={config} />} />
        <Route path="/login" element={<SignIn config={config} />} />
        <Route path="/request-access" element={<RequestAccess config={config} />} />
        <Route path="/admin/login" element={<Navigate to="/login" replace />} />
        <Route path="/portal/login" element={<Navigate to="/login" replace />} />
        <Route
          path="/admin"
          element={
            <RequireAdmin>
              <AdminDashboard config={config} />
            </RequireAdmin>
          }
        />
        <Route
          path="/portal"
          element={
            <RequireClient>
              <PortalHome config={config} />
            </RequireClient>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}
