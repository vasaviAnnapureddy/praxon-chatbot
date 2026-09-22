/**
 * The company logo, from company.yaml -> branding. One place, used everywhere.
 *
 *   kind="header" -> mark + name, no tagline  (top bars)
 *   kind="full"   -> with the tagline         (sign-in page, footer)
 *   kind="mark"   -> just the round symbol    (small square spots)
 *
 * No image set in company.yaml? It shows the name as text instead, so a new
 * company without a logo still gets a working site.
 */
export default function Logo({ config, kind = 'header', className = '' }) {
  const b = config?.branding || {}
  const name = config?.company?.name || ''
  const src = { header: b.logo_url, full: b.logo_full_url || b.logo_url, mark: b.logo_mark_url }[kind]

  if (!src) return <span className={`logo-text ${className}`}>{b.logo_text || name}</span>
  // alt = what screen readers say, and what shows if the image fails to load.
  return <img src={src} alt={name} className={`logo logo-${kind} ${className}`} />
}
