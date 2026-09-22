/**
 * The assistant's face — the same robot as the corner launcher in widget.js.
 *
 * One component so the chat header, the dashboard and (later) the client
 * portal all show the same character. `accent` comes from company.yaml.
 *
 *   <BotAvatar size={38} accent="#07B6A8" />
 *
 *   Q: Why is the drawing duplicated here and in widget.js?
 *   A: widget.js runs on OTHER people's websites and must stay plain JavaScript
 *      with no React. This file is for our own React pages. If you change the
 *      face, change both.
 */
export default function BotAvatar({ size = 38, accent = '#07B6A8', animated = true }) {
  return (
    <svg
      className={animated ? 'bot-avatar animated' : 'bot-avatar'}
      viewBox="0 0 64 64"
      width={size}
      height={size}
      aria-hidden="true"
    >
      <line x1="32" y1="17" x2="32" y2="9" stroke="#fff" strokeWidth="3" strokeLinecap="round" />
      <circle className="bot-tip" cx="32" cy="7" r="4" fill={accent} />
      <rect x="7" y="29" width="5" height="12" rx="2.5" fill="#fff" opacity=".9" />
      <rect x="52" y="29" width="5" height="12" rx="2.5" fill="#fff" opacity=".9" />
      <rect x="11" y="17" width="42" height="36" rx="13" fill="#fff" />
      <rect x="16" y="23" width="32" height="22" rx="9" fill="#10182B" />
      <g className="bot-eyes" fill={accent}>
        <ellipse cx="25.5" cy="32" rx="3.4" ry="4.2" />
        <ellipse cx="38.5" cy="32" rx="3.4" ry="4.2" />
      </g>
      <path
        d="M26.5 39.2 Q32 42.6 37.5 39.2"
        stroke={accent}
        strokeWidth="2.2"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  )
}
