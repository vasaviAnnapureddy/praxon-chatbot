import { useEffect } from 'react'
import Logo from '../components/Logo.jsx'

/**
 * The Praxon landing page — and the pitch itself.
 *
 * Two things make this more than decoration:
 *
 * 1. Every word comes from client/company.yaml through /api/config. Change the
 *    YAML, reload, and the site is a different company. That is the demo: "your
 *    website, with a smart assistant built in, and your content swappable in
 *    minutes."
 *
 * 2. The chatbot is installed EXACTLY the way a real client would install it —
 *    by loading /widget.js with a script tag, in the useEffect below. Not by
 *    importing a React component. If the widget works here, it works pasted
 *    into any WordPress, Wix or hand-written site.
 */
export default function DemoSite({ config }) {
  const company = config.company || {}
  const site = config.site || {}
  const contacts = config.contacts || {}
  const services = site.services || []
  const steps = site.process_steps || []
  const why = site.why_us || []
  const pricing = config.services_preview || []

  useEffect(() => {
    // The real install, one line, the same one a client pastes.
    if (document.querySelector('script[data-praxon-widget]')) return
    const tag = document.createElement('script')
    tag.src = '/widget.js'
    tag.defer = true
    tag.setAttribute('data-praxon-widget', 'true')
    document.body.appendChild(tag)
  }, [])

  // "Talk to us" opens the chat assistant — the thing we are demoing.
  // widget.js exposes window.PraxonChat. If it hasn't loaded yet, the link
  // falls back to its href and scrolls down to the Contact section instead.
  const openChat = (e) => {
    if (window.PraxonChat) {
      e.preventDefault()
      window.PraxonChat.open()
    }
  }

  return (
    <div className="site">
      <header className="nav">
        <a className="nav-logo" href="#top">
          <Logo config={config} />
        </a>
        <nav className="nav-links">
          <a href="#services">Services</a>
          <a href="#process">How we work</a>
          <a href="#pricing">Pricing</a>
          <a href="#contact">Contact</a>
          <a href="/login">Sign in</a>
        </nav>
        <a className="btn btn-primary small" href="#contact" onClick={openChat}>
          {site.hero_cta || 'Talk to us'}
        </a>
      </header>

      {/* ------------------------------------------------------------ hero */}
      <section className="hero" id="top">
        <div className="hero-inner">
          <div className="hero-badge">
            {company.city} · {company.tagline}
          </div>
          <h1>{site.hero_heading}</h1>
          <p className="hero-sub">{site.hero_sub}</p>

          <div className="hero-cta">
            <a className="btn btn-primary" href="#contact" onClick={openChat}>
              {site.hero_cta || 'Talk to us'}
            </a>
            <a className="btn btn-ghost" href="#services">
              {site.hero_cta_secondary || 'See what we build'}
            </a>
          </div>

          <div className="hero-hint">
            <span className="pulse" /> The assistant in the corner answers questions about this
            company — try asking it what a website costs.
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------- services */}
      <section className="section" id="services">
        <h2>{site.sections?.services_heading || 'What we build'}</h2>
        <div className="card-grid">
          {services.map((s) => (
            <article className="card" key={s.title}>
              <div className="card-icon" aria-hidden="true">
                {s.icon}
              </div>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* --------------------------------------------------------- process */}
      <section className="section alt" id="process">
        <h2>{site.sections?.process_heading || 'How we work'}</h2>
        <div className="steps">
          {steps.map((s) => (
            <div className="step" key={s.step}>
              <div className="step-num">{s.step}</div>
              <div>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* --------------------------------------------------------- pricing */}
      <section className="section" id="pricing">
        <h2>Typical ranges</h2>
        <p className="section-sub">
          Ranges, not quotes. The real number comes after a short call, in writing.
        </p>
        <div className="price-list">
          {pricing
            .filter((p) => p.service && p.range)
            .map((p) => (
              <div className="price-row" key={p.service}>
                <span>{p.service}</span>
                <b>{p.range}</b>
              </div>
            ))}
        </div>
      </section>

      {/* ------------------------------------------------------------- why */}
      <section className="section alt" id="why">
        <h2>{site.sections?.why_heading || 'Why teams pick us'}</h2>
        <div className="card-grid">
          {why.map((w) => (
            <article className="card plain" key={w.title}>
              <h3>{w.title}</h3>
              <p>{w.body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* --------------------------------------------------------- contact */}
      <section className="section contact-section" id="contact">
        <h2>{site.sections?.contact_heading || 'Start a conversation'}</h2>
        <p className="section-sub">{contacts.response_promise}</p>

        <div className="contact-grid">
          {contacts.whatsapp_link && (
            <a
              className="contact-card"
              href={contacts.whatsapp_link}
              target="_blank"
              rel="noopener noreferrer"
            >
              <span className="ico">💬</span>
              <b>WhatsApp</b>
              <span>{contacts.phone_display}</span>
            </a>
          )}
          {contacts.booking_url && (
            <a
              className="contact-card"
              href={contacts.booking_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <span className="ico">📅</span>
              <b>Book a call</b>
              <span>30 minutes, free</span>
            </a>
          )}
          {contacts.sales_email && (
            <a className="contact-card" href={`mailto:${contacts.sales_email}`}>
              <span className="ico">✉️</span>
              <b>Email</b>
              <span>{contacts.sales_email}</span>
            </a>
          )}
          {contacts.careers_email && (
            <a className="contact-card" href={`mailto:${contacts.careers_email}`}>
              <span className="ico">💼</span>
              <b>Careers</b>
              <span>{contacts.careers_email}</span>
            </a>
          )}
        </div>
      </section>

      <footer className="site-foot">
        <div>
          <Logo config={config} kind="full" className="foot-logo" />
          <span>{contacts.office_line}</span>
        </div>
        <div className="foot-links">
          <a href="#services">Services</a>
          <a href="#process">Process</a>
          <a href={`mailto:${contacts.sales_email}`}>Contact</a>
          <a href="/login">Sign in</a>
        </div>
        {company.is_demo && <div className="demo-note">{company.demo_notice}</div>}
      </footer>
    </div>
  )
}
