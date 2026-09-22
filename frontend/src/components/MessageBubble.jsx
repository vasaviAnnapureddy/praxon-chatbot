/**
 * One message in the chat.
 *
 * The tiny formatter below handles **bold**, links and line breaks. A full
 * markdown library would be ~40 KB for three features the assistant actually
 * uses, and every kilobyte is a slower first paint on a phone.
 *
 * Everything is escaped before any HTML is produced, so a visitor cannot inject
 * markup into the page by typing it.
 */

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function format(text) {
  let html = escapeHtml(text)

  // Links: http(s), mailto and wa.me all become clickable.
  html = html.replace(
    /(https?:\/\/[^\s<]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>',
  )
  html = html.replace(
    /\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b/g,
    '<a href="mailto:$1">$1</a>',
  )
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/^- (.+)$/gm, '<span class="li">$1</span>')
  html = html.replace(/\n/g, '<br/>')
  return html
}

export default function MessageBubble({ role, content, typing = false }) {
  const isUser = role === 'user'

  return (
    <div className={`msg-row ${isUser ? 'msg-user' : 'msg-bot'}`}>
      <div className="msg-bubble">
        {typing ? (
          <span className="typing" aria-label="Assistant is typing">
            <i /><i /><i />
          </span>
        ) : (
          <span dangerouslySetInnerHTML={{ __html: format(content) }} />
        )}
      </div>
    </div>
  )
}
