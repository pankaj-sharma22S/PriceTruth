import { FormEvent, useEffect, useMemo, useState } from 'react'
import { addDiscoveryCandidate, createTracking, getAlerts, getDiscovery, getHistory, getPlatforms, getProduct, getTracking, inspectProduct, setTracking } from './lib/api'
import type { Candidate, Comparison, DiscoveryRun, Offer, Platform, TrackingJob } from './types'
import './alerts.css'
import './product.css'
import './discovery.css'

const money = (value: string | null, currency: string | null) => value == null ? 'Price unavailable' : new Intl.NumberFormat('en-IN', { style: 'currency', currency: currency || 'INR', maximumFractionDigits: 2 }).format(Number(value))
const time = (value: string | null) => value ? new Date(value).toLocaleString() : 'Not checked'
const platformNames: Record<string,string> = { amazon_india: 'Amazon India', flipkart: 'Flipkart', shopsy: 'Shopsy', myntra: 'Myntra', meesho: 'Meesho', ajio: 'AJIO', croma: 'Croma' }
const statusNames: Record<string,string> = { source_checked: 'Source listing checked', searching: 'Searching', exact_match_found: 'Exact match found', similar_product_found: 'Similar product found', no_match_found: 'No match found', could_not_check: 'Could not check', price_unavailable: 'Price unavailable' }
const canonicalUrl = (value: string) => {
  try {
    const parsed = new URL(value)
    parsed.search = ''
    parsed.hash = ''
    return `${parsed.origin}${parsed.pathname}`.replace(/\/+$/, '').toLowerCase()
  } catch { return value.toLowerCase() }
}

export default function App() {
  const [url, setUrl] = useState('')
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [platforms, setPlatforms] = useState<Platform[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [trackingJobs, setTrackingJobs] = useState<TrackingJob[]>([])
  const [alertMode, setAlertMode] = useState<'any_drop' | 'target_price'>('any_drop')
  const [targetPrice, setTargetPrice] = useState('')
  const [history, setHistory] = useState<{price:string;currency:string;observed_at:string;platform:string}[]>([])
  const [alerts, setAlerts] = useState<{id:number;tracking_id:number;listing_id:number;kind:string;message:string;created_at:string}[]>([])
  const [discovery, setDiscovery] = useState<DiscoveryRun | null>(null)
  const [candidatePlatform, setCandidatePlatform] = useState('')
  const [candidateUrl, setCandidateUrl] = useState('')
  const [candidateBusy, setCandidateBusy] = useState(false)

  useEffect(() => { getPlatforms().then(r => setPlatforms(r.platforms)).catch(() => setPlatforms([])); getTracking().then(r => setTrackingJobs(r.tracking)).catch(() => {}) }, [])
  useEffect(() => { if (comparison?.product.id) { getHistory(comparison.product.id).then(r => setHistory(r.observations)).catch(() => setHistory([])); getProduct(comparison.product.id).then(setComparison).catch(() => {}) } }, [comparison?.product.id])
  useEffect(() => {
    if (!comparison?.product.id) return
    let cancelled = false
    const refresh = async () => {
      try { const r = await getTracking(); if (!cancelled) setTrackingJobs(r.tracking) } catch {}
      try { const r = await getAlerts(); if (!cancelled) setAlerts(r.alerts) } catch {}
    }
    void refresh()
    const timer = window.setInterval(refresh, 15000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [comparison?.product.id])
  useEffect(() => {
    const runId = comparison?.discovery_run_id
    if (!runId) return
    let cancelled = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const result = await getDiscovery(runId)
        if (cancelled) return
        setDiscovery(result)
        if (result.status === 'searching') timer = window.setTimeout(poll, 1200)
      } catch { if (!cancelled) timer = window.setTimeout(poll, 2500) }
    }
    void poll()
    return () => { cancelled = true; if (timer) window.clearTimeout(timer) }
  }, [comparison?.discovery_run_id, discovery?.status])
  useEffect(() => {
    if (discovery?.status !== 'completed' || !comparison?.product.id) return
    getProduct(comparison.product.id).then(setComparison).catch(() => {})
    getHistory(comparison.product.id).then(r => setHistory(r.observations)).catch(() => {})
  }, [discovery?.status, comparison?.product.id])
  const exactOffers: Offer[] = useMemo(() => {
    const source = comparison?.offers ?? []
    const candidates = discovery?.checks.flatMap(check => check.candidates.filter(c => c.match_classification === 'exact').map(c => ({
      id: c.id, listing_id: c.listing_id, platform: c.platform, url: c.url, title: c.title, image_url: c.image_url, price: c.price, currency: c.currency,
      price_type: c.price_type, availability: c.availability, observed_at: c.observed_at, freshness: c.freshness,
      status: c.price == null ? 'partial' : 'success',
      match: { classification: 'exact', evidence: c.match_evidence.evidence ?? [], missing: c.match_evidence.missing ?? [], conflicts: c.match_evidence.conflicts ?? [] },
    } as Offer))) ?? []
    const unique = new Map<string, Offer>()
    for (const offer of [...source, ...candidates]) {
      const key = `${offer.platform}:${canonicalUrl(offer.url)}`
      const previous = unique.get(key)
      // Keep the richest record when a retailer returned tracking/query URL duplicates.
      if (!previous || (!previous.image_url && offer.image_url) || (previous.price == null && offer.price != null)) unique.set(key, offer)
    }
    return [...unique.values()]
  }, [comparison, discovery])
  const similarCandidates: Candidate[] = useMemo(() => {
    const unique = new Map<string, Candidate>()
    for (const candidate of discovery?.checks.flatMap(check => check.candidates.filter(c => c.match_classification === 'probable' || c.match_classification === 'uncertain')) ?? []) {
      const key = `${candidate.platform}:${canonicalUrl(candidate.url)}`
      const previous = unique.get(key)
      if (!previous || (!previous.image_url && candidate.image_url) || (previous.price == null && candidate.price != null)) unique.set(key, candidate)
    }
    return [...unique.values()]
  }, [discovery])
  const winner = discovery?.lowest_verified_offer ?? comparison?.lowest_verified_offer ?? null
  const chart = useMemo(() => {
    const values = history.map(x => Number(x.price)).filter(Number.isFinite)
    if (values.length < 2) return null
    const min = Math.min(...values), max = Math.max(...values), spread = max - min || 1
    return values.map((n, i) => `${(i/(values.length-1))*100},${92-((n-min)/spread)*78}`).join(' ')
  }, [history])

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setComparison(null); setDiscovery(null)
    try { const result = await inspectProduct(url.trim()); setComparison(result) } catch (e) { setError(e instanceof Error ? e.message : 'Could not inspect this product URL.') } finally { setBusy(false) }
  }
  async function addCandidate(event: FormEvent) {
    event.preventDefault()
    if (!comparison?.discovery_run_id || !candidateUrl.trim()) return
    setCandidateBusy(true); setError('')
    try { await addDiscoveryCandidate(comparison.discovery_run_id, candidateUrl.trim()); setCandidateUrl(''); setCandidatePlatform(''); setDiscovery(await getDiscovery(comparison.discovery_run_id)) }
    catch (e) { setError(e instanceof Error ? e.message : 'Candidate link could not be checked.') }
    finally { setCandidateBusy(false) }
  }
  async function track(listingId?: number) {
    if (!comparison) return
    if (alertMode === 'target_price' && (!targetPrice || !Number.isFinite(Number(targetPrice)) || Number(targetPrice) <= 0)) {
      setError('Enter a positive INR target price.')
      return
    }
    setError('')
    try {
      await createTracking(comparison.product.id, alertMode, alertMode === 'target_price' ? Number(targetPrice) : undefined, listingId)
      setTrackingJobs((await getTracking()).tracking)
    } catch (e) { setError(e instanceof Error ? e.message : 'Alert could not be enabled.') }
  }
  async function toggleTracking(jobId: number, active: boolean) {
    try { await setTracking(jobId, active); setTrackingJobs((await getTracking()).tracking) }
    catch (e) { setError(e instanceof Error ? e.message : 'Alert update failed.') }
  }

  return <main className="shell">
    <header className="topbar"><a className="brand" href="#top"><span className="brand-mark">₹</span><span>PriceTruth<span className="brand-ai"> AI</span></span></a><span className="live-label"><i /> Evidence first pricing</span></header>
    <section className="hero" id="top"><div className="eyebrow">A clearer way to compare</div><h1>Find the right price.<br/><em>For the exact product.</em></h1><p>Paste a product page to inspect its verified listing and see which retailer checks are actually available.</p>
      <form className="search" onSubmit={submit}><label className="sr-only" htmlFor="product-url">Product URL</label><span className="search-icon">↗</span><input id="product-url" type="url" required placeholder="Paste a product link from a supported retailer" value={url} onChange={e => setUrl(e.target.value)} /><button disabled={busy}>{busy ? <><span className="spinner"/> Checking</> : 'Check price <span>→</span>'}</button></form>
      <div className="trust"><span>✓ No guessed prices</span><span>✓ Same-variant matching</span><span>✓ Direct retailer links</span></div>
    </section>
    {error && <div className="notice error" role="alert"><b>Couldn’t complete that check</b><span>{error}</span></div>}
    {comparison && <>
      <section className="product-panel"><div><div className="eyebrow">PRODUCT IDENTIFIED</div><h2>{comparison.product.title}</h2><div className="product-meta">{comparison.product.brand && <span>{comparison.product.brand}</span>}{comparison.product.model && <span>Model {comparison.product.model}</span>}</div>{Object.keys(comparison.product.specs).length > 0 && <div className="spec-list">{Object.entries(comparison.product.specs).map(([key,value]) => <span key={key}><b>{key}</b> {value}</span>)}</div>}</div><span className="match-pill">Source listing</span></section>
      <section className="result-grid">
        <article className="winner-card"><div className="card-label">LOWEST VERIFIED COMPARABLE PRICE</div>{winner ? <><strong className="winner-price">{money(winner.price, winner.currency)}</strong><div className="winner-source">{platformNames[winner.platform] ?? winner.platform} · Exact match</div><small className="winner-scope">Among successful checked listings</small><a className="button-link" href={winner.url} target="_blank" rel="noreferrer">View product <span>↗</span></a><small>Checked {time(winner.observed_at)}</small></> : <><strong className="winner-empty">{discovery?.status === 'searching' ? 'Checking comparable offers…' : 'No verified exact offer yet'}</strong><p>Only fresh, exact same-variant listings with verified comparable prices can appear here.</p></>}</article>
        <article className="coverage-card"><div className="section-heading"><div><div className="card-label">PLATFORM COVERAGE</div><h3>Discovery status</h3></div><span className="coverage-count">{discovery ? `${discovery.checks.filter(c => c.status !== 'searching').length}/${platforms.length} checked` : `0/${platforms.length} checked`}</span></div><div className="platform-list">{platforms.map(p => { const check = discovery?.checks.find(x => x.platform === p.key); const state = check?.status ?? (p.key === comparison.product.origin_platform ? 'source_checked' : 'searching'); return <div className="platform-row discovery-row" key={p.key}><span className="platform-name"><i className={`status-dot ${state}`}/>{p.name}</span><span className={`status-text ${state}`}>{statusNames[state] ?? state}</span>{check?.message && <small className="discovery-message">{check.message}</small>}<span className="discovery-actions"><a href={p.manual_search_url} target="_blank" rel="noreferrer">Search manually ↗</a><button onClick={() => { setCandidatePlatform(p.key); setCandidateUrl('') }}>Paste product link</button></span></div> })}</div>{candidatePlatform && <form className="candidate-form" onSubmit={addCandidate}><label htmlFor="candidate-url">Paste a {platformNames[candidatePlatform]} product URL</label><input id="candidate-url" type="url" required value={candidateUrl} onChange={e => setCandidateUrl(e.target.value)} placeholder="https://…"/><button disabled={candidateBusy}>{candidateBusy ? 'Adding…' : 'Check candidate'}</button><button type="button" className="text-button" onClick={() => setCandidatePlatform('')}>Cancel</button></form>}<p className="fine-print">A retailer search page is opened for you; PriceTruth checks only permitted product pages.</p></article>
      </section>
      {exactOffers.length > 0 && <section className="section"><div className="section-heading"><div><div className="eyebrow">VERIFIED EXACT MATCHES</div><h2>Comparable listings</h2></div><span className="muted">{exactOffers.length} checked listing(s)</span></div><div className="table-wrap"><table><thead><tr><th>Retailer</th><th>Product & match</th><th>Price</th><th>Availability</th><th>Last checked</th><th>Offer actions</th></tr></thead><tbody>{exactOffers.map(offer => {
        const sameMode = (job: TrackingJob) => job.mode === alertMode && (job.mode === 'any_drop' || Number(job.target_price) === Number(targetPrice))
        const offerJob = trackingJobs.find(job => job.active && job.listing_id === offer.listing_id && sameMode(job))
        const productJob = trackingJobs.find(job => job.active && job.product_id === comparison.product.id && !job.listing_id && sameMode(job))
        return <tr key={`${offer.platform}:${offer.url}`}><td><b>{platformNames[offer.platform] ?? offer.platform}</b></td><td><div className="listing-title">{offer.image_url && <img className="product-image" src={offer.image_url} alt="" loading="lazy"/>}<span>{offer.title}</span></div><small className="match-text">Exact match{offer.match.evidence.length ? ` | ${offer.match.evidence[0]}` : ''}</small></td><td className="price-cell">{money(offer.price, offer.currency)}<small>{offer.price_type}</small></td><td><span className={`availability ${offer.availability}`}>{offer.availability.replace('_',' ')}</span></td><td className="time-cell">{time(offer.observed_at)}{offer.freshness === 'stale' && <small>Stale - excluded from lowest price</small>}</td><td className="offer-actions"><a className="external" href={offer.url} target="_blank" rel="noreferrer" aria-label={`Open ${platformNames[offer.platform]} listing`}>Open</a>{offerJob ? <><button className="offer-alert" onClick={() => toggleTracking(offerJob.id, false)}>Turn off {offerJob.mode === 'any_drop' ? 'price-drop' : 'target'} alert</button><small>{offerJob.mode === 'any_drop' ? 'Any price drop' : `Target INR ${offerJob.target_price}`} | Last check {time(offerJob.last_checked_at)} | Next {time(offerJob.next_run_at)}</small></> : productJob ? <small>Covered by product alert</small> : offer.listing_id ? <button className="offer-alert" onClick={() => track(offer.listing_id!)}>Enable alert</button> : <small>Alert unavailable until exact listing is saved.</small>}</td></tr>
      })}</tbody></table></div></section>}
      {similarCandidates.length > 0 && <section className="section similar-section"><div className="section-heading"><div><div className="eyebrow">SEPARATE FROM PRICE RANKING</div><h2>Similar products</h2></div><span className="muted">Not included in the lowest-price result | Alerts require an exact variant match</span></div><div className="similar-grid">{similarCandidates.map(candidate => <article className="similar-card" key={`${candidate.platform}:${candidate.url}`}>{candidate.image_url && <img src={candidate.image_url} alt="" loading="lazy"/>}<div className="similar-content"><span className="similar-badge">◇ Similar — Not Exact Match</span><h3>{candidate.title}</h3><p>{platformNames[candidate.platform] ?? candidate.platform} · {money(candidate.price, candidate.currency)}</p><small>{candidate.match_evidence.conflicts.length ? `Differs: ${candidate.match_evidence.conflicts.join(', ')}` : candidate.match_evidence.missing.length ? `Could not verify: ${candidate.match_evidence.missing.join(', ')}` : 'Product variant could not be confirmed.'}</small><a href={candidate.url} target="_blank" rel="noreferrer">View retailer listing ↗</a></div></article>)}</div></section>}
      <section className="result-grid lower-grid"><article className="history-card"><div className="section-heading"><div><div className="eyebrow">OBSERVATIONS</div><h3>Price history</h3></div><span className="muted">{history.length} checked points</span></div>{chart ? <div className="chart"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Price observations over time"><line x1="0" y1="92" x2="100" y2="92"/><polyline points={chart}/></svg></div> : <div className="empty-chart">Price history will appear as verified observations accumulate.</div>}</article>
        <article className="tracking-card"><div className="eyebrow">PRICE ALERTS</div><h3>Keep an eye on this product</h3><p>Product alerts cover verified exact listings. Enable an alert for one exact offer from its row above.</p><label className="target-label" htmlFor="alert-mode">Alert mode</label><select id="alert-mode" className="alert-mode" value={alertMode} onChange={e => setAlertMode(e.target.value as 'any_drop' | 'target_price')}><option value="any_drop">Any price drop</option><option value="target_price">Target price</option></select>{alertMode === 'target_price' && <label className="target-input"><span>INR</span><input id="target" type="number" min="0.01" step="0.01" inputMode="decimal" value={targetPrice} onChange={e => setTargetPrice(e.target.value)} placeholder="Target price in INR"/></label>}<button className="enable-product-alert" onClick={() => track()}>Keep an eye on this product</button>{trackingJobs.filter(job => job.active && job.product_id === comparison.product.id && !job.listing_id).map(job => <div className="tracking-active" key={job.id}><span><i/> {job.mode === 'any_drop' ? 'Any price drop' : `Target ${money(job.target_price, 'INR')}`} active<br/><small>Last check {time(job.last_checked_at)} | Next check {time(job.next_run_at)}</small></span><button className="text-button" onClick={() => toggleTracking(job.id, false)}>Turn off</button></div>)}</article></section>
      {alerts.filter(alert => trackingJobs.some(job => job.id === alert.tracking_id && job.product_id === comparison.product.id)).length > 0 && <section className="section"><div className="section-heading"><div><div className="eyebrow">SAVED ALERT EVENTS</div><h2>Price & availability updates</h2></div></div><div className="alert-list">{alerts.filter(alert => trackingJobs.some(job => job.id === alert.tracking_id && job.product_id === comparison.product.id)).map(alert => <article className="alert-event" key={alert.id}><span className="alert-icon">{alert.kind === 'stock_change' ? 'Stock' : 'Price'}</span><div><b>{alert.kind === 'stock_change' ? 'Availability changed' : alert.kind === 'price_drop' ? 'Price dropped' : 'Target price reached'}</b><p>{alert.message}</p></div><time>{time(alert.created_at)}</time></article>)}</div></section>}
    </>}
    {!comparison && <section className="platform-strip"><div className="section-heading"><div><div className="eyebrow">SUPPORTED URL FORMATS</div><h3>Seven retailer adapters</h3></div><span className="muted">Live access remains unverified</span></div><div className="platform-chips">{(platforms.length ? platforms : [{key:'amazon_india',name:'Amazon India'},{key:'flipkart',name:'Flipkart'},{key:'shopsy',name:'Shopsy'},{key:'myntra',name:'Myntra'},{key:'meesho',name:'Meesho'},{key:'ajio',name:'AJIO'},{key:'croma',name:'Croma'}] as Platform[]).map(p => <span key={p.key}>{p.name}</span>)}</div></section>}
    <footer><span>PriceTruth AI</span><span>Prices and stock are shown only when supported by an observation.</span></footer>
  </main>
}
