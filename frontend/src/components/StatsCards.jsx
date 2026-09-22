/**
 * The numbers row at the top of the dashboard.
 *
 * Note what is NOT shown: no conversion rate, no lead quality score, no
 * "hot leads" count. Counts and labels only. The founder reads the facts and
 * makes the call — that principle holds in the UI as much as in the backend.
 */

function Card({ label, value, sub, tone = '' }) {
  return (
    <div className={`stat-card ${tone}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export default function StatsCards({ stats }) {
  if (!stats) return null

  const timeline = stats.by_timeline || {}
  const llm = stats.llm_today || {}

  return (
    <>
      <div className="stat-grid">
        <Card
          label="Conversations"
          value={stats.total_conversations ?? 0}
          sub={`${stats.conversations_7d ?? 0} in the last 7 days`}
        />
        <Card
          label="Enquiries"
          value={stats.total_leads ?? 0}
          sub={`${stats.leads_7d ?? 0} in the last 7 days`}
        />
        <Card
          label="With contact details"
          value={stats.leads_with_contact ?? 0}
          sub="you can reply to these"
          tone="accent"
        />
        <Card
          label="Unanswered questions"
          value={stats.unanswered_count ?? 0}
          sub="content worth adding"
          tone={stats.unanswered_count > 0 ? 'warn' : ''}
        />
      </div>

      <div className="stat-split">
        <div className="panel">
          <h3>By timeline</h3>
          <p className="panel-note">
            What the visitor said about timing. A label, not a rating.
          </p>
          <ul className="bar-list">
            {[
              'Immediate requirement',
              'Planned requirement',
              'Exploring options',
              'Details pending',
            ].map((label) => {
              const count = timeline[label] || 0
              const total = Math.max(stats.total_leads || 1, 1)
              return (
                <li key={label}>
                  <span className="bar-label">{label}</span>
                  <span className="bar-track">
                    <span className="bar-fill" style={{ width: `${(count / total) * 100}%` }} />
                  </span>
                  <span className="bar-count">{count}</span>
                </li>
              )
            })}
          </ul>
        </div>

        <div className="panel">
          <h3>Most asked</h3>
          <p className="panel-note">The questions visitors actually type.</p>
          <ol className="top-questions">
            {(stats.top_questions || []).slice(0, 8).map((q, i) => (
              <li key={i}>
                <span>{q.question}</span>
                <b>{q.count}</b>
              </li>
            ))}
            {!(stats.top_questions || []).length && <li className="empty">Nothing yet.</li>}
          </ol>
        </div>
      </div>

      <div className="health-strip">
        <span>
          Average time to first word: <b>{stats.avg_first_word_ms || 0} ms</b>
        </span>
        <span>
          LLM calls today: <b>{llm.calls || 0}</b>
        </span>
      </div>
    </>
  )
}
