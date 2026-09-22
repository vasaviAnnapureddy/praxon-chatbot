import { useEffect, useState } from 'react'
import { admin } from '../api.js'
import EditDetails from './EditDetails.jsx'
import TempPassword, { tempInfo } from './TempPassword.jsx'

/**
 * REQUESTS tab — clients who used "Request access" on the sign-in page.
 *
 *   Edit    -> fix a spelling mistake BEFORE approving (the email matters most:
 *              it's where the sign-in details go)
 *   Approve -> makes their CLIENT account and emails them the sign-in details
 *   Reject  -> closes the request; no account is made
 *
 * Nothing happens by itself: a person on the team always decides.
 */
const FIELDS = [['name', 'Name'], ['email', 'Email'], ['company_name', 'Company']]

export default function RequestsPanel({ company, flash, onChange }) {
  const [requests, setRequests] = useState([])
  const [temp, setTemp] = useState(null)
  const [editing, setEditing] = useState(null)
  const [error, setError] = useState('')

  const load = () =>
    admin
      .requests()
      .then((d) => setRequests(d.requests))
      .catch((e) => setError(e.message))
  useEffect(() => {
    load()
  }, [])

  const act = async (r, approve) => {
    setError('')
    const question = approve
      ? `Approve ${r.name}? Their sign-in details will be emailed to ${r.email}.`
      : `Reject the request from ${r.name}? No account will be made.`
    if (!window.confirm(question)) return
    try {
      if (approve) {
        const reply = await admin.approveRequest(r.id)
        setTemp(tempInfo(reply, company, `${reply.user.name || reply.user.email} approved — client account made`))
      } else {
        await admin.rejectRequest(r.id)
        flash('Request rejected')
      }
      load()
      onChange?.()
    } catch (err) {
      setError(err.message)
    }
  }

  const save = async (r, changes) => {
    setError('')
    try {
      await admin.changeRequest(r.id, changes)
      setEditing(null)
      flash('Saved')
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const pending = requests.filter((r) => r.status === 'pending')
  const handled = requests.filter((r) => r.status !== 'pending')

  return (
    <div className="manage">
      {error && <div className="banner error">{error}</div>}
      <TempPassword info={temp} onClose={() => setTemp(null)} />

      <div className="panel">
        <h3>Waiting for a decision</h3>
        <p className="panel-note">Clients who asked for a login. Check the email is spelled right, then approve.</p>
        {!pending.length && <p className="muted small">No requests waiting.</p>}
        {pending.map((r) =>
          editing === r.id ? (
            <EditDetails
              key={r.id}
              person={r}
              fields={FIELDS}
              onSave={(changes) => save(r, changes)}
              onCancel={() => setEditing(null)}
            />
          ) : (
            <div className="person" key={r.id}>
              <div>
                <b>{r.name}</b>
                {r.company_name && <span className="muted small"> · {r.company_name}</span>}
                <div className="muted small">
                  {r.email} · asked {r.created_at}
                </div>
                {r.message && <p className="request-message">{r.message}</p>}
              </div>
              <div className="person-actions">
                <button type="button" className="btn btn-ghost small" onClick={() => setEditing(r.id)}>
                  Edit
                </button>
                <button type="button" className="btn btn-primary small" onClick={() => act(r, true)}>
                  Approve
                </button>
                <button type="button" className="btn btn-ghost small" onClick={() => act(r, false)}>
                  Reject
                </button>
              </div>
            </div>
          ),
        )}
      </div>

      {handled.length > 0 && (
        <div className="panel">
          <h3>Already decided</h3>
          {handled.map((r) => (
            <div className="person off" key={r.id}>
              <div>
                <b>{r.name}</b> <span className="tag">{r.status}</span>
                <div className="muted small">
                  {r.email} · by {r.handled_by || 'someone'} on {r.handled_at}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
