import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ConversationList from '../components/ConversationList.jsx'
import LeadDetail from '../components/LeadDetail.jsx'
import LeadTable from '../components/LeadTable.jsx'
import Logo from '../components/Logo.jsx'
import ProjectsPanel from '../components/ProjectsPanel.jsx'
import RequestsPanel from '../components/RequestsPanel.jsx'
import StatsCards from '../components/StatsCards.jsx'
import TeamPanel from '../components/TeamPanel.jsx'
import UnansweredTable from '../components/UnansweredTable.jsx'
import { admin } from '../api.js'

/**
 * The team's screen. Seven tabs, one job each:
 *
 *   Enquiries          — who got in touch, what they said, what you decided
 *   Conversations      — every chat, including the ones that led nowhere
 *   Unanswered         — what your website is missing
 *   Overview           — the counts
 *   Clients & projects — customers, their projects, updates they see in the portal
 *   Requests           — clients asking for a login ("Request access"); approve or reject
 *   Team               — who can sign in here (only the owner can change it)
 *
 * Everything is read-only except the founder's own status and notes. The bot
 * never writes to those fields, and the founder's decision is never overwritten
 * by a later extraction.
 */
const TABS = [
  ['leads', 'Enquiries'],
  ['conversations', 'Conversations'],
  ['unanswered', 'Unanswered'],
  ['stats', 'Overview'],
  ['projects', 'Clients & projects'],
  ['requests', 'Requests'],
  ['team', 'Team'],
]

export default function AdminDashboard({ config }) {
  const [tab, setTab] = useState('leads')
  const [leads, setLeads] = useState([])
  const [statuses, setStatuses] = useState([])
  const [timelineLabels, setTimelineLabels] = useState([])
  const [conversations, setConversations] = useState([])
  const [unanswered, setUnanswered] = useState([])
  const [stats, setStats] = useState(null)
  const [detail, setDetail] = useState(null)
  const [filters, setFilters] = useState({ status_filter: '', timeline: '', category: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const [me, setMe] = useState(null)        // who is signed in: name + role

  const navigate = useNavigate()

  const flash = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(''), 2600)
  }

  const loadLeads = useCallback(async () => {
    const data = await admin.leads(filters)
    setLeads(data.leads)
    setStatuses(data.statuses)
    setTimelineLabels(data.timeline_labels)
  }, [filters])

  const loadAll = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      const [statsData, convData, unansData] = await Promise.all([
        admin.stats(),
        admin.conversations(),
        admin.unanswered(),
      ])
      setStats(statsData)
      setConversations(convData.conversations)
      setUnanswered(unansData.questions)
      await loadLeads()
    } catch (err) {
      setError(err.message)
      if (err.message.includes('sign in')) navigate('/login', { replace: true })
    } finally {
      setBusy(false)
    }
  }, [loadLeads, navigate])

  useEffect(() => {
    admin.me().then((d) => setMe(d.user)).catch(() => {})
  }, [])

  // Pending access requests, for the number on the Requests tab.
  const [pending, setPending] = useState(0)
  const countRequests = useCallback(
    () => admin.requests().then((d) => setPending(d.requests.filter((r) => r.status === 'pending').length)).catch(() => {}),
    [],
  )
  useEffect(() => {
    countRequests()
  }, [countRequests])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  useEffect(() => {
    loadLeads().catch((e) => setError(e.message))
  }, [filters, loadLeads])

  const openLead = async (id) => {
    try {
      setDetail(await admin.lead(id))
    } catch (err) {
      setError(err.message)
    }
  }

  const changeStatus = async (id, status, notes) => {
    try {
      const { lead } = await admin.setStatus(id, status, notes)
      setLeads((prev) => prev.map((l) => (l.id === id ? { ...l, ...lead } : l)))
      if (detail?.lead?.id === id) setDetail({ ...detail, lead })
      flash('Saved')
    } catch (err) {
      setError(err.message)
    }
  }

  const removeLead = async (id) => {
    try {
      await admin.deleteLead(id)
      setLeads((prev) => prev.filter((l) => l.id !== id))
      setDetail(null)
      flash('Deleted permanently')
      loadAll()
    } catch (err) {
      setError(err.message)
    }
  }

  const resolveQuestion = async (id) => {
    await admin.resolveUnanswered(id)
    setUnanswered((prev) => prev.filter((q) => q.id !== id))
  }

  const signOut = () => {
    admin.logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="admin">
      <header className="admin-bar">
        <div className="admin-brand">
          <Logo config={config} className="admin-logo" />
          <span className="admin-tagline">
            Team dashboard{me ? ` · ${me.name} (${me.role})` : ''}
          </span>
        </div>

        <div className="admin-actions">
          <button type="button" className="btn btn-ghost small" onClick={loadAll} disabled={busy}>
            {busy ? 'Refreshing...' : 'Refresh'}
          </button>
          <button
            type="button"
            className="btn btn-ghost small"
            onClick={() => admin.downloadCsv().catch((e) => setError(e.message))}
          >
            Export CSV
          </button>
          <button
            type="button"
            className="btn btn-ghost small"
            onClick={async () => {
              const r = await admin.testEmail()
              flash(r.sent ? `Test email sent — ${r.detail}` : `Email failed: ${r.detail}`)
            }}
          >
            Test email
          </button>
          <button type="button" className="btn btn-ghost small" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      <nav className="admin-tabs">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={tab === key ? 'tab active' : 'tab'}
            onClick={() => setTab(key)}
          >
            {label}
            {key === 'leads' && leads.length > 0 && <span className="tab-count">{leads.length}</span>}
            {key === 'requests' && pending > 0 && <span className="tab-count warn">{pending}</span>}
            {key === 'unanswered' && unanswered.length > 0 && (
              <span className="tab-count warn">{unanswered.length}</span>
            )}
          </button>
        ))}
      </nav>

      {error && <div className="banner error">{error}</div>}
      {toast && <div className="banner ok">{toast}</div>}

      <main className="admin-main">
        {tab === 'leads' && (
          <>
            <div className="filters">
              <select
                value={filters.status_filter}
                onChange={(e) => setFilters({ ...filters, status_filter: e.target.value })}
              >
                <option value="">All statuses</option>
                {statuses.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>

              <select
                value={filters.timeline}
                onChange={(e) => setFilters({ ...filters, timeline: e.target.value })}
              >
                <option value="">All timelines</option>
                {timelineLabels.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>

              <select
                value={filters.category}
                onChange={(e) => setFilters({ ...filters, category: e.target.value })}
              >
                <option value="">All types</option>
                <option value="enquiry">Enquiries</option>
                <option value="careers">Careers</option>
              </select>
            </div>

            <LeadTable
              leads={leads}
              statuses={statuses}
              onOpen={openLead}
              onStatusChange={changeStatus}
            />
          </>
        )}

        {tab === 'conversations' && <ConversationList conversations={conversations} />}

        {tab === 'unanswered' && (
          <UnansweredTable questions={unanswered} onResolve={resolveQuestion} />
        )}

        {tab === 'stats' && <StatsCards stats={stats} />}

        {tab === 'projects' && me && <ProjectsPanel me={me} company={config.company?.name} flash={flash} />}

        {tab === 'requests' && (
          <RequestsPanel company={config.company?.name} flash={flash} onChange={countRequests} />
        )}

        {tab === 'team' && <TeamPanel me={me} company={config.company?.name} flash={flash} />}
      </main>

      {detail && (
        <LeadDetail
          data={detail}
          statuses={statuses}
          onClose={() => setDetail(null)}
          onStatusChange={changeStatus}
          onDelete={removeLead}
        />
      )}
    </div>
  )
}
