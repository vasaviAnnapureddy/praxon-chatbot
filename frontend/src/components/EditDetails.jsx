import { useState } from 'react'

/**
 * A small inline form to FIX someone's details — usually a spelling mistake in
 * their name or email. Used for team members, clients and access requests.
 *
 *   fields: [['name', 'Name'], ['email', 'Email'], ...]  — which boxes to show
 *   onSave(changes) gets ONLY what actually changed.
 */
export default function EditDetails({ person, fields, note, onSave, onCancel }) {
  const [form, setForm] = useState(() => Object.fromEntries(fields.map(([k]) => [k, person[k] || ''])))
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    const changes = Object.fromEntries(
      Object.entries(form).filter(([k, v]) => v.trim() !== (person[k] || '')),
    )
    if (!Object.keys(changes).length) return onCancel()
    setBusy(true)
    try {
      await onSave(changes)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="edit-details" onSubmit={submit}>
      {fields.map(([key, label]) => (
        <label key={key}>
          {label}
          <input
            type={key === 'email' ? 'email' : 'text'}
            value={form[key]}
            required={key === 'email'}
            onChange={(e) => setForm({ ...form, [key]: e.target.value })}
          />
        </label>
      ))}
      {note && <p className="muted small">{note}</p>}
      <div className="row-actions">
        <button type="submit" className="btn btn-primary small" disabled={busy}>
          {busy ? 'Saving...' : 'Save'}
        </button>
        <button type="button" className="btn btn-ghost small" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}
