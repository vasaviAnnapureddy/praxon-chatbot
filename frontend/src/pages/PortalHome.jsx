import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Logo from '../components/Logo.jsx'
import { ProjectStatus, UpdateFeed } from '../components/ProjectTimeline.jsx'
import { portal } from '../api.js'

/**
 * The CLIENT PORTAL — what a Praxon customer sees after signing in.
 *
 *   - their projects (and only theirs — the server filters, not this page)
 *   - for the open project: stage, progress, dates, every team update
 *   - a box to reply; the team sees it in their dashboard timeline
 *
 * One project opens straight away; several show as a list to pick from.
 */
export default function PortalHome({ config }) {
  const [me, setMe] = useState(null)
  const [projects, setProjects] = useState(null)       // null = still loading
  const [open, setOpen] = useState(null)               // { project, updates, stages }
  const [reply, setReply] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const bounce = (err) => {
    setError(err.message)
    if (err.message.includes('sign in')) navigate('/login', { replace: true })
  }

  const openProject = (id) => portal.project(id).then(setOpen).catch(bounce)

  useEffect(() => {
    Promise.all([portal.me(), portal.projects()])
      .then(([m, p]) => {
        setMe(m.user)
        setProjects(p.projects)
        if (p.projects.length === 1) openProject(p.projects[0].id)   // just one? show it
      })
      .catch(bounce)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const send = async (e) => {
    e.preventDefault()
    if (!reply.trim()) return
    setSending(true)
    try {
      await portal.reply(open.project.id, reply.trim())
      setReply('')
      openProject(open.project.id)
    } catch (err) {
      bounce(err)
    } finally {
      setSending(false)
    }
  }

  const signOut = () => {
    portal.logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="portal">
      <header className="portal-bar">
        <div className="portal-brand">
          <Logo config={config} kind="mark" className="portal-logo" />
          <div>
            <b>{config.company?.name}</b>
            <span className="muted small"> · Client portal</span>
          </div>
        </div>
        <div className="portal-user">
          {me && (
            <span className="small">
              {me.name}
              {me.company_name ? ` · ${me.company_name}` : ''}
            </span>
          )}
          <button type="button" className="btn btn-ghost small" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      <main className="portal-main">
        {error && <div className="banner error">{error}</div>}

        {projects === null && <div className="spinner" />}

        {projects?.length === 0 && (
          <div className="empty-state">
            <h3>No projects yet</h3>
            <p>Your project will appear here as soon as the team sets it up.</p>
          </div>
        )}

        {projects?.length > 1 && (
          <div className="portal-tabs">
            {projects.map((p) => (
              <button
                type="button"
                key={p.id}
                className={`project-item ${open?.project.id === p.id ? 'active' : ''}`}
                onClick={() => openProject(p.id)}
              >
                <b>{p.name}</b>
                <span className="muted small">
                  {p.stage} · {p.progress}%
                </span>
              </button>
            ))}
          </div>
        )}

        {open && (
          <>
            <section className="panel">
              <h1 className="portal-title">{open.project.name}</h1>
              {open.project.summary && <p className="psummary">{open.project.summary}</p>}
              <ProjectStatus project={open.project} stages={open.stages} />
              <div className="muted small">Last updated {open.project.updated_at}</div>
            </section>

            <form className="panel reply-box" onSubmit={send}>
              <h3>Message the team</h3>
              <textarea
                rows={3}
                value={reply}
                placeholder="A question, feedback, or content you want to send..."
                onChange={(e) => setReply(e.target.value)}
              />
              <button type="submit" className="btn btn-primary" disabled={sending || !reply.trim()}>
                {sending ? 'Sending...' : 'Send'}
              </button>
            </form>

            <section className="panel">
              <h3>Updates</h3>
              <UpdateFeed updates={open.updates} viewer="client" />
            </section>
          </>
        )}
      </main>
    </div>
  )
}
