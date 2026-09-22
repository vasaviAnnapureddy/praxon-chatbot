import { useEffect, useState } from 'react'
import { admin } from '../api.js'
import { ProjectStatus, UpdateFeed } from './ProjectTimeline.jsx'
import EditDetails from './EditDetails.jsx'
import TempPassword, { tempInfo } from './TempPassword.jsx'

/**
 * CLIENTS & PROJECTS tab.
 *
 *   left  : clients (add one) and their projects (create one)
 *   right : the open project — change stage / progress / dates, post updates,
 *           read the client's replies. The preview at the top is EXACTLY what
 *           the client sees in their portal.
 *
 * Who sees which projects (the server decides; this only mirrors it):
 *   owner -> every project, and chooses who works on each one
 *   team  -> only the projects they are assigned to
 */
const NEW_CLIENT = { email: '', name: '', company_name: '', send_email: true }
const CLIENT_FIELDS = [['name', 'Name'], ['email', 'Email'], ['company_name', 'Company']]

export default function ProjectsPanel({ me, company, flash }) {
  const isOwner = me?.role === 'owner'
  const [team, setTeam] = useState([])            // for the owner's "who works on it" boxes
  const [temp, setTemp] = useState(null)
  const [editing, setEditing] = useState(null)    // id of the client being edited
  const [clients, setClients] = useState([])
  const [projects, setProjects] = useState([])
  const [stages, setStages] = useState([])
  const [open, setOpen] = useState(null)          // { project, updates }
  const [clientForm, setClientForm] = useState(NEW_CLIENT)
  const [projectForm, setProjectForm] = useState({ client_id: '', name: '', target_date: '' })
  const [edit, setEdit] = useState(null)          // editable copy of the open project
  const [update, setUpdate] = useState({ title: '', body: '' })
  const [error, setError] = useState('')

  const fail = (e) => setError(e.message)

  const load = async () => {
    const [c, p] = await Promise.all([admin.clients(), admin.projects()])
    setClients(c.clients)
    setProjects(p.projects)
    setStages(p.stages)
  }
  useEffect(() => {
    load().catch(fail)
  }, [])
  useEffect(() => {
    if (isOwner) admin.team().then((d) => setTeam(d.team.filter((u) => u.is_active))).catch(fail)
  }, [isOwner])

  const openProject = async (id) => {
    setError('')
    const data = await admin.project(id).catch(fail)
    if (!data) return
    setOpen(data)
    setEdit({ ...data.project, member_ids: data.project.members.map((m) => m.id) })
  }

  const addClient = async (e) => {
    e.preventDefault()
    setError('')
    try {
      const reply = await admin.addClient(clientForm)
      const { user } = reply
      setClientForm(NEW_CLIENT)
      setProjectForm((f) => ({ ...f, client_id: String(user.id) }))   // ready for their first project
      setTemp(tempInfo(reply, company, `${user.name || user.email} added — now create their project`))
      load()
    } catch (err) {
      fail(err)
    }
  }

  const createProject = async (e) => {
    e.preventDefault()
    setError('')
    try {
      const { project } = await admin.createProject({
        client_id: Number(projectForm.client_id),
        name: projectForm.name,
        target_date: projectForm.target_date || null,
      })
      setProjectForm({ client_id: '', name: '', target_date: '' })
      flash('Project created')
      await load()
      openProject(project.id)
    } catch (err) {
      fail(err)
    }
  }

  const saveProject = async () => {
    setError('')
    try {
      await admin.changeProject(edit.id, {
        name: edit.name,
        summary: edit.summary,
        stage: edit.stage,
        progress: Number(edit.progress),
        start_date: edit.start_date || null,
        target_date: edit.target_date || null,
        ...(isOwner ? { member_ids: edit.member_ids } : {}),   // only the owner assigns people
      })
      flash('Saved — the client sees this now')
      await load()
      openProject(edit.id)
    } catch (err) {
      fail(err)
    }
  }

  const postUpdate = async (e) => {
    e.preventDefault()
    setError('')
    try {
      await admin.postUpdate(open.project.id, update)
      setUpdate({ title: '', body: '' })
      flash('Update posted to the client')
      openProject(open.project.id)
    } catch (err) {
      fail(err)
    }
  }

  const removeProject = async () => {
    if (!window.confirm(`Delete "${open.project.name}" and all its updates? This cannot be undone.`)) return
    try {
      await admin.deleteProject(open.project.id)
      setOpen(null)
      flash('Project deleted')
      load()
    } catch (err) {
      fail(err)
    }
  }

  const sendSignIn = async (c) => {
    const note = c.must_change_password ? '' : ' Their current password will stop working.'
    if (!window.confirm(`Email ${c.email} a new temporary password?${note}`)) return
    try {
      const reply = await admin.sendSignIn(c.id)
      setTemp(tempInfo(reply, company, `New sign-in details for ${reply.user.name || reply.user.email}`))
      load()
    } catch (err) {
      fail(err)
    }
  }

  const saveClient = async (c, changes) => {
    setError('')
    try {
      const { user } = await admin.changeUser(c.id, changes)
      setEditing(null)
      flash(
        changes.email && user.must_change_password
          ? 'Saved. The old sign-in details stopped working — click "Send new sign-in details".'
          : 'Saved',
      )
      load()
    } catch (err) {
      fail(err)
    }
  }

  const toggleMember = (id) =>
    setEdit((e) => ({
      ...e,
      member_ids: e.member_ids.includes(id) ? e.member_ids.filter((x) => x !== id) : [...e.member_ids, id],
    }))

  const toggleClient = async (c) => {
    try {
      await admin.changeUser(c.id, { is_active: !c.is_active })
      flash(c.is_active ? 'Client switched off — signed out now' : 'Client switched back on')
      load()
    } catch (err) {
      fail(err)
    }
  }

  return (
    <div className="projects-layout">
      <div className="projects-side">
        {error && <div className="banner error">{error}</div>}
        <TempPassword info={temp} onClose={() => setTemp(null)} />

        {/* ------------------------------------------------ clients */}
        <div className="panel">
          <h3>Clients</h3>
          {!clients.length && <p className="muted small">No clients yet. Add one below.</p>}
          {clients.map((c) =>
            editing === c.id ? (
              <EditDetails
                key={c.id}
                person={c}
                fields={CLIENT_FIELDS}
                note="Changing the email stops any sign-in details already sent, in case they went to the wrong address."
                onSave={(changes) => saveClient(c, changes)}
                onCancel={() => setEditing(null)}
              />
            ) : (
            <div className={`person ${c.is_active ? '' : 'off'}`} key={c.id}>
              <div>
                <b>{c.name || c.email}</b>
                {c.company_name && <span className="muted small"> · {c.company_name}</span>}
                {!c.is_active && <span className="tag">switched off</span>}
                {c.must_change_password && !c.temp_expired && <span className="tag">waiting for first sign-in</span>}
                {c.temp_expired && <span className="tag warn">sign-in details expired — send new</span>}
                <div className="muted small">
                  {c.email} · {c.project_count} project{c.project_count === 1 ? '' : 's'}
                  {c.last_login ? ` · last in ${c.last_login}` : ' · never signed in'}
                </div>
              </div>
              <div className="person-actions">
                <button type="button" className="btn btn-ghost small" onClick={() => setEditing(c.id)}>
                  Edit
                </button>
                <button type="button" className="btn btn-ghost small" onClick={() => sendSignIn(c)}>
                  Send new sign-in details
                </button>
                <button type="button" className="btn btn-ghost small" onClick={() => toggleClient(c)}>
                  {c.is_active ? 'Switch off' : 'Switch on'}
                </button>
              </div>
            </div>
            ),
          )}
        </div>

        <form className="panel form-grid" onSubmit={addClient}>
          <h3>Add a client</h3>
          <label>
            Email <span className="req">required</span>
            <input type="email" required value={clientForm.email} onChange={(e) => setClientForm({ ...clientForm, email: e.target.value })} />
          </label>
          <label>
            Name
            <input value={clientForm.name} onChange={(e) => setClientForm({ ...clientForm, name: e.target.value })} />
          </label>
          <label>
            Company
            <input value={clientForm.company_name} onChange={(e) => setClientForm({ ...clientForm, company_name: e.target.value })} />
          </label>
          <label className="check">
            <input type="checkbox" checked={clientForm.send_email} onChange={(e) => setClientForm({ ...clientForm, send_email: e.target.checked })} />
            Email the sign-in details to them now
          </label>
          <button type="submit" className="btn btn-primary">Add client</button>
        </form>

        {/* ------------------------------------------------ projects */}
        <div className="panel">
          <h3>{isOwner ? 'Projects' : 'My projects'}</h3>
          {!projects.length && (
            <p className="muted small">
              {isOwner ? 'No projects yet.' : 'No projects assigned to you yet. The owner assigns them.'}
            </p>
          )}
          {projects.map((p) => (
            <button
              type="button"
              key={p.id}
              className={`project-item ${open?.project.id === p.id ? 'active' : ''}`}
              onClick={() => openProject(p.id)}
            >
              <b>{p.name}</b>
              <span className="muted small">
                {p.client_name} · {p.stage} · {p.progress}%
                {isOwner && ` · ${p.members.length ? p.members.map((m) => m.name).join(', ') : 'nobody assigned'}`}
              </span>
            </button>
          ))}
        </div>

        {clients.length > 0 && (
          <form className="panel form-grid" onSubmit={createProject}>
            <h3>New project</h3>
            <label>
              Client <span className="req">required</span>
              <select required value={projectForm.client_id} onChange={(e) => setProjectForm({ ...projectForm, client_id: e.target.value })}>
                <option value="">Choose…</option>
                {clients.filter((c) => c.is_active).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name || c.email}
                    {c.company_name ? ` — ${c.company_name}` : ''}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Project name <span className="req">required</span>
              <input required value={projectForm.name} onChange={(e) => setProjectForm({ ...projectForm, name: e.target.value })} />
            </label>
            <label>
              Target date
              <input type="date" value={projectForm.target_date} onChange={(e) => setProjectForm({ ...projectForm, target_date: e.target.value })} />
            </label>
            <button type="submit" className="btn btn-primary">Create project</button>
          </form>
        )}
      </div>

      {/* ------------------------------------------------ the open project */}
      <div className="projects-main">
        {!open ? (
          <div className="empty-state">
            <h3>Choose a project</h3>
            <p>Or add a client, then create their first project.</p>
          </div>
        ) : (
          <>
            <div className="panel">
              <div className="pmain-head">
                <div>
                  <h2>{open.project.name}</h2>
                  <div className="muted small">
                    {open.project.client_name}
                    {open.project.client_company ? ` · ${open.project.client_company}` : ''} · updated{' '}
                    {open.project.updated_at}
                  </div>
                </div>
                <span className="tag">What the client sees ↓</span>
              </div>
              <ProjectStatus project={open.project} stages={open.stages} />
              {open.project.summary && <p className="psummary">{open.project.summary}</p>}
            </div>

            <div className="panel form-grid two">
              <h3>Change the status</h3>
              <label>
                Stage
                <select value={edit.stage} onChange={(e) => setEdit({ ...edit, stage: e.target.value })}>
                  {open.stages.map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label>
                Progress: <b>{edit.progress}%</b>
                <input type="range" min="0" max="100" step="5" value={edit.progress} onChange={(e) => setEdit({ ...edit, progress: e.target.value })} />
              </label>
              <label>
                Start date
                <input type="date" value={edit.start_date} onChange={(e) => setEdit({ ...edit, start_date: e.target.value })} />
              </label>
              <label>
                Target date
                <input type="date" value={edit.target_date} onChange={(e) => setEdit({ ...edit, target_date: e.target.value })} />
              </label>
              <label className="span2">
                Summary <span className="muted">(what the project is, in one or two lines)</span>
                <textarea rows={2} value={edit.summary} onChange={(e) => setEdit({ ...edit, summary: e.target.value })} />
              </label>
              <div className="span2">
                Team on this project
                {isOwner ? (
                  <div className="member-picks">
                    {team.map((u) => (
                      <label key={u.id} className="check">
                        <input type="checkbox" checked={edit.member_ids.includes(u.id)} onChange={() => toggleMember(u.id)} />
                        {u.name} <span className="muted small">({u.role})</span>
                      </label>
                    ))}
                    <p className="muted small">Team members see only the projects they are ticked on. You see all.</p>
                  </div>
                ) : (
                  <p className="muted small">
                    {open.project.members.map((m) => m.name).join(', ') || 'nobody'} · only the owner changes this
                  </p>
                )}
              </div>
              <div className="span2 row-actions">
                <button type="button" className="btn btn-primary" onClick={saveProject}>Save</button>
                {isOwner && (
                  <button type="button" className="btn btn-danger small" onClick={removeProject}>Delete project</button>
                )}
              </div>
            </div>

            <form className="panel form-grid" onSubmit={postUpdate}>
              <h3>Post an update to the client</h3>
              <label>
                Title <span className="muted">(optional)</span>
                <input value={update.title} placeholder="Homepage design approved" onChange={(e) => setUpdate({ ...update, title: e.target.value })} />
              </label>
              <label>
                Update <span className="req">required</span>
                <textarea rows={3} required value={update.body} placeholder="What happened, what's next, anything you need from them." onChange={(e) => setUpdate({ ...update, body: e.target.value })} />
              </label>
              <button type="submit" className="btn btn-primary">Post update</button>
            </form>

            <div className="panel">
              <h3>Timeline</h3>
              <UpdateFeed updates={open.updates} viewer="team" />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
