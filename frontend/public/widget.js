/**
 * widget.js — the ONE file a client pastes into their website.
 *
 *   <script src="https://your-app.onrender.com/widget.js" defer></script>
 *
 * Hard rules this file obeys (feature i, issue #8):
 *
 * 1. NO React, no framework, no dependency. Plain JavaScript, small, because it
 *    runs on somebody else's website and must not slow it down.
 * 2. The chat lives in an IFRAME: their CSS can't break our chat, ours can't
 *    break their site, and their JavaScript can't read the conversation.
 * 3. The iframe is built only on first hover/tap. The page pays almost nothing.
 * 4. Opening the launcher also wakes the database, so the first reply is fast.
 * 5. Everything is namespaced (pxn-). One guarded global flag, one small API.
 *
 * THE LAUNCHER (the button in the corner)
 *   A friendly robot face — not a speech bubble — so it reads as "assistant",
 *   not "message". It floats, blinks, its antenna pulses, and it tilts its head
 *   on hover. A greeting card appears after a few seconds, because a greeting
 *   is what actually gets people to click.
 *
 *   All of it is configurable from client/company.yaml:
 *     branding.primary_color / accent_color   -> colours
 *     branding.launcher_style                 -> "bot" (default) or "classic"
 *     chat.launcher_greeting                  -> the greeting card text ("" = off)
 *
 *   Q: Why SVG drawn in code instead of an image file?
 *   A: No extra download, it stays sharp at any size, and the colours can follow
 *      company.yaml. An image would need a new file per client.
 */
;(function () {
  'use strict'

  if (window.__praxonWidgetLoaded) return
  window.__praxonWidgetLoaded = true

  // The origin this script came from — so the same file works on localhost,
  // on Render and on a real domain without being edited.
  var script = document.currentScript
  var ORIGIN = (function () {
    try { return new URL(script.src).origin } catch (e) { return window.location.origin }
  })()

  var state = { open: false, built: false, warmed: false, position: 'right', style: 'bot' }
  var TEASER_KEY = 'pxn_teaser_closed'

  // ------------------------------------------------------------------ icons
  // The robot face. Colours come in as arguments so they follow company.yaml.
  //   head  -> white rounded square       visor -> dark screen
  //   eyes  -> accent colour, they blink  antenna tip -> pulses
  function botSvg(accent) {
    return (
      '<svg class="pxn-bot" viewBox="0 0 64 64" width="46" height="46" aria-hidden="true">' +
        '<line x1="32" y1="17" x2="32" y2="9" stroke="#fff" stroke-width="3" stroke-linecap="round"/>' +
        '<circle class="pxn-tip" cx="32" cy="7" r="4" fill="' + accent + '"/>' +
        '<rect x="7" y="29" width="5" height="12" rx="2.5" fill="#fff" opacity=".9"/>' +
        '<rect x="52" y="29" width="5" height="12" rx="2.5" fill="#fff" opacity=".9"/>' +
        '<rect x="11" y="17" width="42" height="36" rx="13" fill="#fff"/>' +
        '<rect x="16" y="23" width="32" height="22" rx="9" fill="#10182B"/>' +
        '<g class="pxn-eyes" fill="' + accent + '">' +
          '<ellipse cx="25.5" cy="32" rx="3.4" ry="4.2"/>' +
          '<ellipse cx="38.5" cy="32" rx="3.4" ry="4.2"/>' +
        '</g>' +
        '<path d="M26.5 39.2 Q32 42.6 37.5 39.2" stroke="' + accent + '" stroke-width="2.2" ' +
          'fill="none" stroke-linecap="round"/>' +
      '</svg>'
    )
  }
  var CLASSIC_ICON = '<span style="font-size:26px;line-height:1">&#128172;</span>'
  var CLOSE_ICON =
    '<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">' +
    '<path d="M6 6l12 12M18 6L6 18" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/></svg>'

  // ---------------------------------------------------------------- styles
  // --pxn-brand / --pxn-accent are set on the launcher from company.yaml.
  var css =
    // launcher button
    '.pxn-launch{position:fixed;bottom:20px;z-index:2147483000;width:64px;height:64px;' +
    'border-radius:22px;border:none;cursor:pointer;padding:0;display:flex;align-items:center;' +
    'justify-content:center;color:#fff;' +
    'background:linear-gradient(145deg,var(--pxn-brand,#1F4FD8),var(--pxn-accent,#07B6A8));' +
    'box-shadow:0 10px 30px rgba(16,24,43,.30),inset 0 1px 0 rgba(255,255,255,.25);' +
    'transition:transform .25s cubic-bezier(.34,1.56,.64,1),border-radius .25s ease;' +
    'animation:pxn-float 3.2s ease-in-out infinite}' +
    '.pxn-launch:hover{transform:scale(1.08) rotate(-8deg);animation-play-state:paused}' +
    '.pxn-launch:focus-visible{outline:3px solid #fff;outline-offset:3px}' +
    '.pxn-launch.pxn-open{border-radius:50%;animation:none}' +
    '.pxn-right{right:20px}.pxn-left{left:20px}' +
    // soft glow ring behind the launcher
    '.pxn-launch::before{content:"";position:absolute;inset:-6px;border-radius:26px;z-index:-1;' +
    'background:var(--pxn-accent,#07B6A8);opacity:.25;filter:blur(10px);' +
    'animation:pxn-glow 2.6s ease-in-out infinite}' +
    '.pxn-launch.pxn-open::before{display:none}' +
    // robot details
    '.pxn-eyes{transform-origin:32px 32px;animation:pxn-blink 4.2s infinite}' +
    '.pxn-tip{transform-origin:32px 7px;animation:pxn-pulse 1.8s ease-in-out infinite}' +
    // greeting card
    '.pxn-teaser{position:fixed;bottom:96px;z-index:2147483000;max-width:260px;' +
    'background:#fff;color:#10182B;border-radius:16px;padding:14px 34px 14px 16px;' +
    'font:500 14px/1.45 "Segoe UI",system-ui,-apple-system,sans-serif;cursor:pointer;' +
    'box-shadow:0 14px 40px rgba(16,24,43,.22);opacity:0;transform:translateY(10px) scale(.96);' +
    'transition:opacity .3s ease,transform .3s cubic-bezier(.34,1.56,.64,1);pointer-events:none}' +
    '.pxn-teaser.pxn-show{opacity:1;transform:none;pointer-events:auto}' +
    '.pxn-teaser b{display:block;font-weight:700;margin-bottom:2px}' +
    '.pxn-teaser-x{position:absolute;top:6px;right:8px;border:0;background:none;cursor:pointer;' +
    'font:400 18px/1 system-ui;color:#8a93a3;padding:4px}' +
    '.pxn-teaser-x:hover{color:#10182B}' +
    // chat window
    '.pxn-frame{position:fixed;bottom:96px;z-index:2147483000;width:392px;height:600px;' +
    'max-height:calc(100vh - 120px);border:0;border-radius:18px;background:#fff;' +
    'box-shadow:0 22px 60px rgba(16,24,43,.30);opacity:0;transform:translateY(12px) scale(.98);' +
    'transition:opacity .2s ease,transform .2s ease;pointer-events:none}' +
    '.pxn-frame.pxn-show{opacity:1;transform:none;pointer-events:auto}' +
    // animations
    '@keyframes pxn-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}' +
    '@keyframes pxn-glow{0%,100%{opacity:.18;transform:scale(.95)}50%{opacity:.38;transform:scale(1.05)}}' +
    '@keyframes pxn-blink{0%,92%,100%{transform:scaleY(1)}95%{transform:scaleY(.1)}}' +
    '@keyframes pxn-pulse{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.35);opacity:.6}}' +
    // phones: full-screen chat, smaller greeting
    '@media(max-width:480px){.pxn-frame{width:100%;height:100%;max-height:100%;bottom:0;' +
    'right:0;left:0;border-radius:0}.pxn-launch{bottom:16px}.pxn-teaser{bottom:90px;max-width:220px;' +
    'font-size:13px}}' +
    // respect "reduce motion" on the visitor's device
    '@media(prefers-reduced-motion:reduce){.pxn-launch,.pxn-launch::before,.pxn-eyes,.pxn-tip' +
    '{animation:none!important}.pxn-launch,.pxn-teaser{transition:none}}'

  function injectStyles() {
    var tag = document.createElement('style')
    tag.setAttribute('data-praxon', 'widget')
    tag.textContent = css
    document.head.appendChild(tag)
  }

  // ------------------------------------------------------------- storage
  // Browsers can block storage (private mode). Never let that break the widget.
  function stored(key) { try { return sessionStorage.getItem(key) } catch (e) { return null } }
  function store(key, v) { try { sessionStorage.setItem(key, v) } catch (e) { /* ignore */ } }

  // ------------------------------------------------------------- warm-up
  // Wakes Neon so the visitor's first real message is not slow.
  function warm() {
    if (state.warmed) return
    state.warmed = true
    try { fetch(ORIGIN + '/api/warmup', { method: 'POST', keepalive: true }).catch(function () {}) }
    catch (e) { /* never let the host page see an error from us */ }
  }

  // ------------------------------------------------------------ elements
  var launcher, frame, teaser, accent = '#07B6A8'

  function sideClass() { return state.position === 'left' ? 'pxn-left' : 'pxn-right' }

  function idleIcon() { return state.style === 'classic' ? CLASSIC_ICON : botSvg(accent) }

  function buildFrame() {
    if (state.built) return
    state.built = true
    frame = document.createElement('iframe')
    frame.className = 'pxn-frame ' + sideClass()
    frame.src = ORIGIN + '/chat'
    frame.title = 'Chat with us'
    frame.setAttribute('loading', 'lazy')
    frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups')
    document.body.appendChild(frame)
  }

  function open() {
    warm()
    buildFrame()
    hideTeaser(true)
    state.open = true
    requestAnimationFrame(function () { frame.classList.add('pxn-show') })
    launcher.innerHTML = CLOSE_ICON
    launcher.classList.add('pxn-open')
    launcher.setAttribute('aria-expanded', 'true')
    launcher.setAttribute('aria-label', 'Close chat')
  }

  function close() {
    state.open = false
    if (frame) frame.classList.remove('pxn-show')
    launcher.innerHTML = idleIcon()
    launcher.classList.remove('pxn-open')
    launcher.setAttribute('aria-expanded', 'false')
    launcher.setAttribute('aria-label', 'Open chat assistant')
  }

  function toggle() { state.open ? close() : open() }

  function buildLauncher() {
    launcher = document.createElement('button')
    launcher.type = 'button'
    launcher.className = 'pxn-launch ' + sideClass()
    launcher.innerHTML = idleIcon()
    launcher.setAttribute('aria-label', 'Open chat assistant')
    launcher.setAttribute('aria-expanded', 'false')
    launcher.addEventListener('click', toggle)
    // Hover starts loading the chat BEFORE the click lands, so it opens instantly.
    launcher.addEventListener('mouseenter', function () { warm(); buildFrame() })
    document.body.appendChild(launcher)
  }

  // ------------------------------------------------------- greeting card
  function buildTeaser(botName, text) {
    if (!text || stored(TEASER_KEY)) return
    teaser = document.createElement('div')
    teaser.className = 'pxn-teaser ' + sideClass()
    teaser.setAttribute('role', 'status')
    teaser.innerHTML = '<b></b><span></span>' +
      '<button type="button" class="pxn-teaser-x" aria-label="Dismiss">&times;</button>'
    // textContent, never innerHTML, for text from config — no HTML injection.
    teaser.querySelector('b').textContent = 'Hi! 👋 I’m ' + botName
    teaser.querySelector('span').textContent = text
    teaser.addEventListener('click', function (e) {
      if (e.target.classList.contains('pxn-teaser-x')) { hideTeaser(true); return }
      open()
    })
    document.body.appendChild(teaser)
    // Appear after 3 s — soon enough to be seen, late enough not to feel pushy.
    setTimeout(function () { if (!state.open && teaser) teaser.classList.add('pxn-show') }, 3000)
  }

  function hideTeaser(remember) {
    if (!teaser) return
    teaser.classList.remove('pxn-show')
    if (remember) store(TEASER_KEY, '1')     // don't nag again this visit
  }

  // ---------------------------------------------------------- config
  function applyConfig(cfg) {
    var b = (cfg && cfg.branding) || {}
    var chat = (cfg && cfg.chat) || {}
    accent = b.accent_color || accent
    if (b.primary_color) launcher.style.setProperty('--pxn-brand', b.primary_color)
    if (b.accent_color) launcher.style.setProperty('--pxn-accent', b.accent_color)
    state.style = b.launcher_style === 'classic' ? 'classic' : 'bot'

    var pos = b.bubble_position === 'left' ? 'left' : 'right'
    if (pos !== state.position) {
      state.position = pos
      launcher.className = 'pxn-launch ' + sideClass() + (state.open ? ' pxn-open' : '')
    }
    if (!state.open) launcher.innerHTML = idleIcon()   // redraw in the real colours

    buildTeaser(chat.bot_name || 'the assistant', chat.launcher_greeting)
  }

  // Let the chat page tell us to close (the X inside the iframe).
  window.addEventListener('message', function (event) {
    if (event.origin !== ORIGIN) return
    if (event.data === 'praxon:close') close()
  })

  // Escape closes the chat, like every other dialog on the web.
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && state.open) close()
  })

  // ------------------------------------------------------------- start
  function start() {
    injectStyles()
    // Drawn immediately with default colours, so the visitor never waits on a
    // network call to see it. The real colours arrive a moment later.
    buildLauncher()
    fetch(ORIGIN + '/api/config')
      .then(function (r) { return r.json() })
      .then(applyConfig)
      .catch(function () { /* the launcher still works with defaults */ })
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start)
  else start()

  // Small public API, e.g. for the site's own "Talk to us" button:
  //   PraxonChat.open()
  window.PraxonChat = { open: open, close: close, toggle: toggle }
})()
