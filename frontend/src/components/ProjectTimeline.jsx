/**
 * How a project LOOKS — shared by the team dashboard and the client portal, so
 * the team always sees exactly what the client sees.
 *
 *   <ProjectStatus project={p} stages={[...]} />   stage stepper + progress + dates
 *   <UpdateFeed updates={[...]} />                  the timeline, newest first
 */

function formatDate(iso) {
  if (!iso) return ''
  // "2026-11-15" -> "15 Nov 2026". Built by hand so the browser's time zone
  // can't shift a date-only value to the previous day.
  const [y, m, d] = iso.split('-').map(Number)
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${d} ${months[m - 1]} ${y}`
}

export function ProjectStatus({ project, stages = [] }) {
  const current = Math.max(0, stages.indexOf(project.stage))
  const progress = Math.min(100, Math.max(0, project.progress || 0))

  return (
    <div className="pstatus">
      <div className="pstatus-top">
        <div>
          <div className="pstatus-label">Current stage</div>
          <div className="pstatus-stage">{project.stage}</div>
        </div>
        <div className="pstatus-pct">{progress}%</div>
      </div>

      <div
        className="pbar"
        role="progressbar"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <span style={{ width: `${progress}%` }} />
      </div>

      <ol className="stepper">
        {stages.map((s, i) => (
          <li key={s} className={i < current ? 'done' : i === current ? 'now' : ''}>
            <span className="dot" aria-hidden="true">
              {i < current ? '✓' : i + 1}
            </span>
            <span className="step-name">{s}</span>
          </li>
        ))}
      </ol>

      {(project.start_date || project.target_date) && (
        <div className="pdates">
          {project.start_date && (
            <span>
              Started <b>{formatDate(project.start_date)}</b>
            </span>
          )}
          {project.target_date && (
            <span>
              Target <b>{formatDate(project.target_date)}</b>
            </span>
          )}
        </div>
      )}
    </div>
  )
}

export function UpdateFeed({ updates = [], viewer = 'team' }) {
  if (!updates.length) {
    return <p className="muted small">No updates yet.</p>
  }
  return (
    <ul className="feed">
      {updates.map((u) => {
        const fromClient = u.author_role === 'client'
        // Label from the viewer's side: the client reads "You", the team reads "Client".
        const who = fromClient ? (viewer === 'client' ? 'You' : `${u.author_name} (client)`) : u.author_name
        return (
          <li key={u.id} className={fromClient ? 'from-client' : 'from-team'}>
            <div className="feed-head">
              <b>{who}</b>
              <span>{u.created_at}</span>
            </div>
            {u.title && <div className="feed-title">{u.title}</div>}
            <div className="feed-body">{u.body}</div>
          </li>
        )
      })}
    </ul>
  )
}
