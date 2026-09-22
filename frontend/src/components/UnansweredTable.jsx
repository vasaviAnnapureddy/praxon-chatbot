/**
 * Questions the assistant could not answer from the content.
 *
 * This is the most commercially useful screen in the dashboard and the easiest
 * to undersell in a pitch. It is a to-do list, written by real visitors, of
 * exactly what the company's website is missing. Every row is a customer who
 * wanted something and did not find it.
 *
 * Fixing a row is a two-minute job: add a paragraph to a .md file in client/content,
 * re-run ingest, mark it done.
 */
export default function UnansweredTable({ questions = [], onResolve }) {
  if (!questions.length) {
    return (
      <div className="empty-state">
        <h3>Nothing unanswered</h3>
        <p>Every question so far has been answered from your content. That is the goal.</p>
      </div>
    )
  }

  return (
    <div className="unanswered">
      <p className="panel-note">
        Add an answer for these to <code>client/content/faqs.md</code>, run{' '}
        <code>python backend/scripts/ingest.py</code>, then mark them done.
      </p>

      {questions.map((q) => (
        <div className="unans-row" key={q.id}>
          <div className="unans-q">
            <span className="unans-text">{q.question}</span>
            <span className="unans-meta">
              asked {q.times_asked}×{q.language !== 'en' ? ` · ${q.language}` : ''} · last{' '}
              {q.last_asked_at}
            </span>
          </div>
          <button type="button" className="btn btn-ghost small" onClick={() => onResolve(q.id)}>
            Mark done
          </button>
        </div>
      ))}
    </div>
  )
}
