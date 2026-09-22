import { useEffect, useState } from 'react'
import { admin } from '../api.js'
import EditDetails from './EditDetails.jsx'
import TempPassword, { tempInfo } from './TempPassword.jsx'

/**
 * The TEAM tab. Everyone on the team can see who is on it; only the OWNER can
 * add people, fix their details, switch them off, or send new sign-in details.
 * (The server enforces that too — hiding the buttons is for tidiness, not security.)
 *
 * Adding someone makes a TEMPORARY password and, with the box ticked, emails it
 * to them in the same click. They choose their own when they first sign in.
 */
const EMPTY = { email: '', name: '', username: '', send_email: true }
const FIELDS = [['name', 'Name'], ['email', 'Email'], ['username', 'Username (optional)']]

export default function TeamPanel({ me, company, flash }) {
  const [team, setTeam] = useState([])
  const [form, setForm] = useState(EMPTY)
  const [temp, setTemp] = useState(null)
  const [editing, setEditing] = useState(null)   // id of the person being edited
  const [error, setError] = useState('')
  const isOwner = me?.role === 'owner'

  const load = () => admin.team().then((d) => setTeam(d.team)).catch((e) => setError(e.message))
  useEffect(() => {
    load()
  }, [])

  const add = async (e) => {
    e.preventDefault()
    setError('')
    try {
      const reply = await admin.addTeamMember(form)
      setForm(EMPTY)
      setTemp(tempInfo(reply, company, `${reply.user.name || reply.user.email} added to the team`))
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const save = async (u, changes) => {
    setError('')
    try {
      const { user } = await admin.changeUser(u.id, changes)
      setEditing(null)
      flash(
        changes.email && user.must_change_password
          ? 'Saved. The old sign-in details stopped working — click "Send new sign-in details".'
          : 'Saved',
      )
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const toggle = async (u) => {
    try {
      await admin.changeUser(u.id, { is_active: !u.is_active })
      flash(u.is_active ? 'Switched off — they are signed out now' : 'Switched back on')
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const sendSignIn = async (u) => {
    const note = u.must_change_password ? '' : ' Their current password will stop working.'
    if (!window.confirm(`Email ${u.email} a new temporary password?${note}`)) return
    try {
      const reply = await admin.sendSignIn(u.id)
      setTemp(tempInfo(reply, company, `New sign-in details for ${reply.user.name || reply.user.email}`))
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="manage">
      {error && <div className="banner error">{error}</div>}
      <TempPassword info={temp} onClose={() => setTemp(null)} />

      <div className="panel">
        <h3>Team</h3>
        <p className="panel-note">People who can open this dashboard.</p>
        <div className="people">
          {team.map((u) =>
            editing === u.id ? (
              <EditDetails
                key={u.id}
                person={u}
                fields={FIELDS}
                note="Changing the email stops any sign-in details already sent, in case they went to the wrong address."
                onSave={(changes) => save(u, changes)}
                onCancel={() => setEditing(null)}
              />
            ) : (
              <div className={`person ${u.is_active ? '' : 'off'}`} key={u.id}>
                <div>
                  <b>{u.name}</b> <span className={`tag role-${u.role}`}>{u.role}</span>
                  {!u.is_active && <span className="tag">switched off</span>}
                  {u.must_change_password && !u.temp_expired && <span className="tag">waiting for first sign-in</span>}
                  {u.temp_expired && <span className="tag warn">sign-in details expired — send new</span>}
                  <div className="muted small">
                    {u.email}
                    {u.username ? ` · ${u.username}` : ''}
                    {u.last_login ? ` · last in ${u.last_login}` : ' · never signed in'}
                  </div>
                </div>
                {isOwner && (
                  <div className="person-actions">
                    <button type="button" className="btn btn-ghost small" onClick={() => setEditing(u.id)}>
                      Edit
                    </button>
                    {u.id !== me.id && (
                      <>
                        <button type="button" className="btn btn-ghost small" onClick={() => sendSignIn(u)}>
                          Send new sign-in details
                        </button>
                        <button type="button" className="btn btn-ghost small" onClick={() => toggle(u)}>
                          {u.is_active ? 'Switch off' : 'Switch on'}
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            ),
          )}
        </div>
      </div>

      {isOwner ? (
        <form className="panel form-grid" onSubmit={add}>
          <h3>Add a team member</h3>
          <label>
            Email <span className="req">required</span>
            <input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </label>
          <label>
            Name
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
          <label>
            Username <span className="muted">(optional)</span>
            <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value.replace(/\s/g, '') })} />
          </label>
          <label className="check">
            <input type="checkbox" checked={form.send_email} onChange={(e) => setForm({ ...form, send_email: e.target.checked })} />
            Email the sign-in details to them now
          </label>
          <button type="submit" className="btn btn-primary">Add to team</button>
        </form>
      ) : (
        <p className="muted small">Only the owner can add or change team members.</p>
      )}
    </div>
  )
}
