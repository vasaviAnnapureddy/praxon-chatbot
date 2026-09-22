/**
 * Two kinds of tappable buttons, one component.
 *
 * 1. Quick questions — shown when the chat opens. These are the ones whose
 *    answers are cached on the server, so tapping one feels instant.
 *
 * 2. Lead chips — budget and timeline options from company.yaml. Tapping is far
 *    easier than typing "₹2 lakh to ₹5 lakh" on a phone, which is the whole
 *    reason the budget answer rate goes up when you offer chips.
 *
 * The "Skip" button matters as much as the chips: it tells the backend the
 * visitor declined, and that question is then never asked again in this
 * conversation.
 */

export default function QuickReplies({
  items = [],
  onPick,
  variant = 'quick',
  onSkip,
  disabled = false,
}) {
  if (!items.length) return null

  return (
    <div className={`chips chips-${variant}`}>
      {items.map((item) => (
        <button
          key={item}
          type="button"
          className="chip"
          disabled={disabled}
          onClick={() => onPick(item)}
        >
          {item}
        </button>
      ))}

      {variant === 'lead' && onSkip && (
        <button type="button" className="chip chip-skip" disabled={disabled} onClick={onSkip}>
          Skip
        </button>
      )}
    </div>
  )
}
