import { FormEvent, useEffect, useMemo, useState } from 'react'
import {
  addDiscoveryCandidate,
  createTracking,
  deleteTracking,
  getAlerts,
  getDataCalculations,
  getDiscovery,
  getHistory,
  getPlatforms,
  getProduct,
  getTracking,
  inspectProduct,
  updateTracking,
} from './lib/api'
import type { AlertEvent, Candidate, Comparison, DataCalculations, DiscoveryRun, Offer, Platform, TrackingJob } from './types'
import { saveProduct } from './lib/api'
import { supabase, setAccessToken } from './lib/supabaseClient'
import { AuthModal } from './components/AuthModal'
import { PriceHistoryChart } from './components/PriceHistoryChart'
import { UserAccountSection } from './components/UserAccountSection'
import './styles.css'
import './alerts.css'
import './product.css'
import './discovery.css'
import './app_enhanced.css'

const money = (value: string | number | null | undefined, currency: string | null = 'INR') => {
  if (value == null || value === '') return 'Price unavailable'
  const num = Number(value)
  if (!Number.isFinite(num)) return 'Price unavailable'
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: currency || 'INR', maximumFractionDigits: 2 }).format(num)
}

const time = (value: string | null | undefined) => (value ? new Date(value).toLocaleString() : 'Not checked')

const platformNames: Record<string, string> = {
  amazon_india: 'Amazon India',
  flipkart: 'Flipkart',
  shopsy: 'Shopsy',
  myntra: 'Myntra',
  meesho: 'Meesho',
  ajio: 'AJIO',
  croma: 'Croma',
}

const canonicalUrl = (value: string) => {
  try {
    const parsed = new URL(value)
    parsed.search = ''
    parsed.hash = ''
    return `${parsed.origin}${parsed.pathname}`.replace(/\/+$/, '').toLowerCase()
  } catch {
    return value.toLowerCase()
  }
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'compare' | 'data-calc' | 'alerts' | 'account'>('compare')
  const [currentUser, setCurrentUser] = useState<any | null>(null)
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [historyChartOpen, setHistoryChartOpen] = useState(false)
  const [savedSuccess, setSavedSuccess] = useState(false)
  const [url, setUrl] = useState('')
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [platforms, setPlatforms] = useState<Platform[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // Filter & sort states
  const [selectedRetailer, setSelectedRetailer] = useState<string>('all')
  const [matchFilter, setMatchFilter] = useState<'all' | 'exact' | 'similar'>('all')
  const [stockFilter, setStockFilter] = useState<'all' | 'in_stock'>('all')
  const [sortBy, setSortBy] = useState<'price_asc' | 'discount_desc' | 'recent'>('price_asc')

  // Alert & tracking state
  const [trackingJobs, setTrackingJobs] = useState<TrackingJob[]>([])
  const [alerts, setAlerts] = useState<AlertEvent[]>([])
  const [history, setHistory] = useState<{ price: string; currency: string; observed_at: string; platform: string }[]>([])
  const [discovery, setDiscovery] = useState<DiscoveryRun | null>(null)
  const [dataCalc, setDataCalc] = useState<DataCalculations | null>(null)

  // Candidate submission
  const [candidatePlatform, setCandidatePlatform] = useState('')
  const [candidateUrl, setCandidateUrl] = useState('')
  const [candidateBusy, setCandidateBusy] = useState(false)

  // Alert Modal state
  const [alertModalOpen, setAlertModalOpen] = useState(false)
  const [alertTargetListingId, setAlertTargetListingId] = useState<number | undefined>(undefined)
  const [alertTargetListingTitle, setAlertTargetListingTitle] = useState<string>('')
  const [alertMode, setAlertMode] = useState<TrackingJob['mode']>('any_drop')
  const [alertTargetPrice, setAlertTargetPrice] = useState<string>('')
  const [alertThresholdPercent, setAlertThresholdPercent] = useState<string>('5')
  const [alertInterval, setAlertInterval] = useState<number>(360)
  const [alertName, setAlertName] = useState<string>('')
  const [alertBusy, setAlertBusy] = useState(false)

  useEffect(() => {
    getPlatforms().then(r => setPlatforms(r.platforms)).catch(() => setPlatforms([]))
    getTracking().then(r => setTrackingJobs(r.tracking)).catch(() => {})
    getAlerts().then(r => setAlerts(r.alerts)).catch(() => {})

    supabase.auth.getSession().then(({ data }) => {
      if (data.session) {
        setAccessToken(data.session.access_token)
        setCurrentUser(data.session.user)
      }
    })

    const { data: authListener } = supabase.auth.onAuthStateChange((_event, session) => {
      setAccessToken(session?.access_token ?? null)
      setCurrentUser(session?.user ?? null)
    })

    return () => {
      authListener.subscription.unsubscribe()
    }
  }, [])

  const handleSaveProductClick = async () => {
    if (!currentUser) {
      setAuthModalOpen(true)
      return
    }
    if (!comparison?.product.id) return
    try {
      await saveProduct(comparison.product.id)
      setSavedSuccess(true)
      setTimeout(() => setSavedSuccess(false), 3000)
    } catch (e: any) {
      alert(e.message || 'Failed to save product')
    }
  }

  const handleSignOut = async () => {
    await supabase.auth.signOut()
    setAccessToken(null)
    setCurrentUser(null)
    setActiveTab('compare')
  }

  useEffect(() => {
    if (activeTab === 'data-calc') {
      getDataCalculations().then(setDataCalc).catch(() => {})
    }
  }, [activeTab])

  useEffect(() => {
    if (comparison?.product.id) {
      getHistory(comparison.product.id).then(r => setHistory(r.observations)).catch(() => setHistory([]))
      getProduct(comparison.product.id).then(setComparison).catch(() => {})
    }
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
      } catch {
        if (!cancelled) timer = window.setTimeout(poll, 2500)
      }
    }
    void poll()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [comparison?.discovery_run_id, discovery?.status])

  useEffect(() => {
    if (discovery?.status !== 'completed' || !comparison?.product.id) return
    getProduct(comparison.product.id).then(setComparison).catch(() => {})
    getHistory(comparison.product.id).then(r => setHistory(r.observations)).catch(() => {})
    getDataCalculations().then(setDataCalc).catch(() => {})
  }, [discovery?.status, comparison?.product.id])

  // Extract deduplicated exact offers
  const exactOffers: Offer[] = useMemo(() => {
    const source = comparison?.offers ?? []
    const candidates =
      (discovery?.checks ?? []).flatMap(check =>
        (check.candidates ?? [])
          .filter(c => c.match_classification === 'exact')
          .map(
            c =>
              ({
                id: c.id,
                listing_id: c.listing_id,
                platform: c.platform,
                url: c.url,
                title: c.title,
                image_url: c.image_url,
                price: c.price,
                mrp: c.mrp,
                discount_percent: c.discount_percent,
                currency: c.currency,
                price_type: c.price_type,
                availability: c.availability,
                observed_at: c.observed_at,
                freshness: c.freshness,
                status: c.price == null ? 'partial' : 'success',
                match: {
                  classification: 'exact',
                  evidence: Array.isArray(c.match_evidence?.evidence) ? c.match_evidence.evidence : [],
                  missing: Array.isArray(c.match_evidence?.missing) ? c.match_evidence.missing : [],
                  conflicts: Array.isArray(c.match_evidence?.conflicts) ? c.match_evidence.conflicts : [],
                },
              } as Offer)
          )
      ) ?? []

    const unique = new Map<string, Offer>()
    for (const offer of [...source, ...candidates]) {
      const key = `${offer.platform}:${canonicalUrl(offer.url)}`
      const previous = unique.get(key)
      if (!previous || (!previous.image_url && offer.image_url) || (previous.price == null && offer.price != null)) {
        unique.set(key, offer)
      }
    }
    return [...unique.values()]
  }, [comparison, discovery])

  // Deduplicated similar candidates
  const similarCandidates: Candidate[] = useMemo(() => {
    const unique = new Map<string, Candidate>()
    for (const candidate of (discovery?.checks ?? []).flatMap(check =>
      (check.candidates ?? []).filter(c => c.match_classification === 'probable' || c.match_classification === 'uncertain')
    )) {
      const key = `${candidate.platform}:${canonicalUrl(candidate.url)}`
      const previous = unique.get(key)
      if (!previous || (!previous.image_url && candidate.image_url) || (previous.price == null && candidate.price != null)) {
        unique.set(key, candidate)
      }
    }
    return [...unique.values()]
  }, [discovery])

  // Filtered & sorted exact offers
  const filteredExactOffers = useMemo(() => {
    let list = exactOffers.filter(o => {
      if (selectedRetailer !== 'all' && o.platform !== selectedRetailer) return false
      if (stockFilter === 'in_stock' && o.availability?.toLowerCase() !== 'in_stock') return false
      return true
    })

    list.sort((a, b) => {
      if (sortBy === 'price_asc') {
        const pa = a.price ? Number(a.price) : Infinity
        const pb = b.price ? Number(b.price) : Infinity
        return pa - pb
      }
      if (sortBy === 'discount_desc') {
        const da = a.discount_percent ? Number(a.discount_percent) : 0
        const db = b.discount_percent ? Number(b.discount_percent) : 0
        return db - da
      }
      if (sortBy === 'recent') {
        const ta = a.observed_at ? new Date(a.observed_at).getTime() : 0
        const tb = b.observed_at ? new Date(b.observed_at).getTime() : 0
        return tb - ta
      }
      return 0
    })
    return list
  }, [exactOffers, selectedRetailer, stockFilter, sortBy])

  // Filtered & sorted similar candidates
  const filteredSimilarCandidates = useMemo(() => {
    let list = similarCandidates.filter(c => {
      if (selectedRetailer !== 'all' && c.platform !== selectedRetailer) return false
      if (stockFilter === 'in_stock' && c.availability?.toLowerCase() !== 'in_stock') return false
      return true
    })

    list.sort((a, b) => {
      if (sortBy === 'price_asc') {
        const pa = a.price ? Number(a.price) : Infinity
        const pb = b.price ? Number(b.price) : Infinity
        return pa - pb
      }
      if (sortBy === 'discount_desc') {
        const da = a.discount_percent ? Number(a.discount_percent) : 0
        const db = b.discount_percent ? Number(b.discount_percent) : 0
        return db - da
      }
      if (sortBy === 'recent') {
        const ta = a.observed_at ? new Date(a.observed_at).getTime() : 0
        const tb = b.observed_at ? new Date(b.observed_at).getTime() : 0
        return tb - ta
      }
      return 0
    })
    return list
  }, [similarCandidates, selectedRetailer, stockFilter, sortBy])

  const winner = discovery?.lowest_verified_offer ?? comparison?.lowest_verified_offer ?? null

  // Price history chart with Alert Target Lines
  const chartData = useMemo(() => {
    const valid = history.filter(x => x.price && Number.isFinite(Number(x.price)))
    if (valid.length < 2) return null

    const prices = valid.map(x => Number(x.price))
    const minPrice = Math.min(...prices)
    const maxPrice = Math.max(...prices)
    const spread = maxPrice - minPrice || 1

    const points = prices
      .map((p, i) => {
        const x = (i / (prices.length - 1)) * 100
        const y = 90 - ((p - minPrice) / spread) * 75
        return `${x},${y}`
      })
      .join(' ')

    // Active target alerts for this product
    const activeTargets = trackingJobs
      .filter(j => j.active && j.product_id === comparison?.product.id && j.mode === 'target_price' && j.target_price)
      .map(j => {
        const tp = Number(j.target_price)
        const y = 90 - ((tp - minPrice) / spread) * 75
        return { target: tp, y: Math.max(5, Math.min(95, y)) }
      })

    return { points, minPrice, maxPrice, activeTargets, count: valid.length }
  }, [history, trackingJobs, comparison?.product.id])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setComparison(null)
    setDiscovery(null)
    try {
      const result = await inspectProduct(url.trim())
      setComparison(result)
      setActiveTab('compare')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not inspect this product URL.')
    } finally {
      setBusy(false)
    }
  }

  async function addCandidate(event: FormEvent) {
    event.preventDefault()
    if (!comparison?.discovery_run_id || !candidateUrl.trim()) return
    setCandidateBusy(true)
    setError('')
    try {
      await addDiscoveryCandidate(comparison.discovery_run_id, candidateUrl.trim())
      setCandidateUrl('')
      setCandidatePlatform('')
      setDiscovery(await getDiscovery(comparison.discovery_run_id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Candidate link could not be checked.')
    } finally {
      setCandidateBusy(false)
    }
  }

  function openAlertModal(listingId?: number, listingTitle?: string) {
    setAlertTargetListingId(listingId)
    setAlertTargetListingTitle(listingTitle || comparison?.product.title || 'Product Alert')
    setAlertMode('any_drop')
    setAlertTargetPrice('')
    setAlertThresholdPercent('5')
    setAlertInterval(360)
    setAlertName('')
    setAlertModalOpen(true)
  }

  async function saveAlert(event: FormEvent) {
    event.preventDefault()
    if (!comparison) return
    setAlertBusy(true)
    setError('')
    try {
      const tp = alertMode === 'target_price' ? Number(alertTargetPrice) : undefined
      const dp = alertMode === 'percent_drop' ? Number(alertThresholdPercent) : undefined
      await createTracking(
        comparison.product.id,
        alertMode,
        tp,
        dp,
        alertInterval,
        alertName || `${platformNames[alertMode] || alertMode} Alert`,
        alertTargetListingId
      )
      setTrackingJobs((await getTracking()).tracking)
      setAlertModalOpen(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to configure alert.')
    } finally {
      setAlertBusy(false)
    }
  }

  async function toggleTrackingJob(jobId: number, currentActive: boolean) {
    try {
      await updateTracking(jobId, { active: !currentActive })
      setTrackingJobs((await getTracking()).tracking)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update alert status.')
    }
  }

  async function removeTrackingJob(jobId: number) {
    if (!confirm('Are you sure you want to delete this alert?')) return
    try {
      await deleteTracking(jobId)
      setTrackingJobs((await getTracking()).tracking)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete alert.')
    }
  }

  const activeAlertsForProduct = useMemo(() => {
    if (!comparison) return []
    return trackingJobs.filter(j => j.product_id === comparison.product.id)
  }, [trackingJobs, comparison])

  return (
    <main className="shell">
      {/* Top Navbar */}
      <header className="topbar">
        <a className="brand" href="#top" onClick={() => setActiveTab('compare')}>
          <span className="brand-mark">₹</span>
          <span>
            PriceTruth<span className="brand-ai"> AI</span>
          </span>
        </a>
        <span className="live-label">
          <i /> Evidence-first Indian Pricing
        </span>

        {/* Navigation Tabs */}
        <nav className="nav-tabs">
          <button
            className={`nav-tab-btn ${activeTab === 'compare' ? 'active' : ''}`}
            onClick={() => setActiveTab('compare')}
          >
            <span>🔍 Price Comparison</span>
          </button>
          <button
            className={`nav-tab-btn ${activeTab === 'data-calc' ? 'active' : ''}`}
            onClick={() => setActiveTab('data-calc')}
          >
            <span>📊 Data & Calculations</span>
          </button>
          <button
            className={`nav-tab-btn ${activeTab === 'alerts' ? 'active' : ''}`}
            onClick={() => setActiveTab('alerts')}
          >
            <span>🔔 Saved Alerts ({trackingJobs.filter(j => j.active).length})</span>
          </button>
          {currentUser ? (
            <button
              className={`nav-tab-btn ${activeTab === 'account' ? 'active' : ''}`}
              onClick={() => setActiveTab('account')}
              style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <span>👤 My Account</span>
            </button>
          ) : (
            <button
              className="nav-tab-btn"
              onClick={() => setAuthModalOpen(true)}
              style={{ background: '#2563eb', color: '#ffffff', fontWeight: 600, border: 'none' }}
            >
              <span>🔑 Sign In / Register</span>
            </button>
          )}
        </nav>
      </header>

      {/* Hero Search Section */}
      {activeTab === 'compare' && (
        <section className="hero" id="top">
          <div className="eyebrow">A Clearer Way to Compare Indian Retailers</div>
          <h1>
            Find the right price.
            <br />
            <em>For the exact product.</em>
          </h1>
          <p>
            Paste any product link from Amazon, Flipkart, Shopsy, Myntra, Meesho, AJIO, or Croma to compare verified prices and track alerts.
          </p>
          <form className="search" onSubmit={submit}>
            <label className="sr-only" htmlFor="product-url">
              Product URL
            </label>
            <span className="search-icon">↗</span>
            <input
              id="product-url"
              type="url"
              required
              placeholder="Paste a product link from a supported Indian retailer..."
              value={url}
              onChange={e => setUrl(e.target.value)}
            />
            <button disabled={busy}>
              {busy ? (
                <>
                  <span className="spinner" /> Checking…
                </>
              ) : (
                <>Check price <span>→</span></>
              )}
            </button>
          </form>
          <div className="trust">
            <span>✓ No guessed prices</span>
            <span>✓ Same-variant matching</span>
            <span>✓ Multi-alert monitoring</span>
            <span>✓ Direct retailer links</span>
          </div>
        </section>
      )}

      {error && (
        <div className="notice error" role="alert">
          <b>Notice:</b>
          <span>{error}</span>
        </div>
      )}

      {/* TAB 1: PRICE COMPARISON */}
      {activeTab === 'compare' && comparison && (() => {
        const heroImage = comparison.product.image_url || filteredExactOffers.find(o => o.image_url)?.image_url || similarCandidates.find(c => c.image_url)?.image_url
        return (
        <>
          {/* Identified Product Header */}
          <section className="product-panel">
            <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
              {heroImage && (
                <div style={{ width: '84px', height: '84px', minWidth: '84px', background: '#f8faf9', borderRadius: '12px', padding: '6px', border: '1px solid #e3eae6', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                  <img src={heroImage} alt={comparison.product.title} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} referrerPolicy="no-referrer" />
                </div>
              )}
              <div>
                <div className="eyebrow">PRODUCT IDENTIFIED</div>
                <h2>{comparison.product.title}</h2>
              <div className="product-meta">
                {comparison.product.brand && <span>Brand: {comparison.product.brand}</span>}
                {comparison.product.model && <span>Model: {comparison.product.model}</span>}
                {comparison.product.origin_platform && (
                  <span>Source: {platformNames[comparison.product.origin_platform] || comparison.product.origin_platform}</span>
                )}
              </div>
              {comparison.product.specs && typeof comparison.product.specs === 'object' && Object.keys(comparison.product.specs).length > 0 && (
                <div className="spec-list">
                  {Object.entries(comparison.product.specs).map(([key, value]) => (
                    <span key={key}>
                      <b>{key}:</b> {typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}
                    </span>
                  ))}
                </div>
              )}
              </div>
            </div>
            <div style={{ display: 'flex', gap: '8px', alignSelf: 'flex-start', flexWrap: 'wrap' }}>
              <button className="btn-set-alert" style={{ padding: '8px 14px', fontSize: '11px' }} onClick={() => openAlertModal()}>
                🔔 Track Product Alerts
              </button>
              <button
                className="btn-set-alert"
                style={{ padding: '8px 14px', fontSize: '11px', background: savedSuccess ? '#16a34a' : '#0f172a' }}
                onClick={handleSaveProductClick}
              >
                {savedSuccess ? '✓ Saved' : '💖 Save Product'}
              </button>
              <button
                className="btn-set-alert"
                style={{ padding: '8px 14px', fontSize: '11px', background: '#2563eb' }}
                onClick={() => setHistoryChartOpen(true)}
              >
                📈 Price History Chart
              </button>
            </div>
          </section>

          {/* Results Summary: Lowest Verified Price + Discovery Status Strip */}
          <section className="result-grid">
            <article className="winner-card">
              <div className="card-label">LOWEST VERIFIED COMPARABLE PRICE</div>
              {winner ? (
                <>
                  <strong className="winner-price">{money(winner.price, winner.currency)}</strong>
                  <div className="winner-source">
                    {platformNames[winner.platform] ?? winner.platform} · Exact match
                  </div>
                  <small className="winner-scope">Among verified and checked listings</small>
                  <a className="button-link" href={winner.url} target="_blank" rel="noreferrer">
                    View product <span>↗</span>
                  </a>
                  <small>Checked {time(winner.observed_at)}</small>
                </>
              ) : (
                <>
                  <strong className="winner-empty">
                    {discovery?.status === 'searching' ? 'Verifying comparable offers…' : 'No verified exact offer yet'}
                  </strong>
                  <p>Only fresh, exact same-variant listings with verified prices appear here.</p>
                </>
              )}
            </article>

            {/* Platform Coverage: Clean compact status with NO failure card clutter */}
            <article className="coverage-card">
              <div className="section-heading">
                <div>
                  <div className="card-label">PLATFORM COVERAGE</div>
                  <h3>Discovery Status</h3>
                </div>
                <span className="coverage-count">
                  {discovery?.checks && Array.isArray(discovery.checks)
                    ? `${discovery.checks.filter(c => c.status !== 'searching').length}/${platforms.length} Checked`
                    : `0/${platforms.length} Checked`}
                </span>
              </div>
              <div className="platform-list">
                {platforms.map(p => {
                  const check = discovery?.checks?.find(x => x.platform === p.key)
                  const state = check?.status ?? (p.key === comparison?.product?.origin_platform ? 'source_checked' : 'searching')
                  return (
                    <div className="platform-row discovery-row" key={p.key}>
                      <span className="platform-name">
                        <i className={`status-dot ${state}`} />
                        {p.name}
                      </span>
                      <span className={`status-text ${state}`}>
                        {state === 'source_checked'
                          ? 'Source Verified'
                          : state === 'exact_match_found'
                          ? 'Exact Match'
                          : state === 'similar_product_found'
                          ? 'Similar Found'
                          : state === 'searching'
                          ? 'Searching'
                          : 'Checked'}
                      </span>
                      <span className="discovery-actions">
                        <a href={p.manual_search_url} target="_blank" rel="noreferrer">
                          Search ↗
                        </a>
                        <button
                          onClick={() => {
                            setCandidatePlatform(p.key)
                            setCandidateUrl('')
                          }}
                        >
                          + Paste link
                        </button>
                      </span>
                    </div>
                  )
                })}
              </div>
              {candidatePlatform && (
                <form className="candidate-form" onSubmit={addCandidate}>
                  <label htmlFor="candidate-url">
                    Paste {platformNames[candidatePlatform]} product URL:
                  </label>
                  <input
                    id="candidate-url"
                    type="url"
                    required
                    value={candidateUrl}
                    onChange={e => setCandidateUrl(e.target.value)}
                    placeholder="https://..."
                  />
                  <button disabled={candidateBusy}>{candidateBusy ? 'Adding…' : 'Check link'}</button>
                  <button type="button" className="text-button" onClick={() => setCandidatePlatform('')}>
                    Cancel
                  </button>
                </form>
              )}
            </article>
          </section>

          {/* Interactive Filters & Sorting Toolbar */}
          <section className="filter-toolbar">
            <div className="filter-group">
              <span className="filter-label">Retailer:</span>
              <button
                className={`filter-pill ${selectedRetailer === 'all' ? 'active' : ''}`}
                onClick={() => setSelectedRetailer('all')}
              >
                All Retailers
              </button>
              {platforms.map(p => (
                <button
                  key={p.key}
                  className={`filter-pill ${selectedRetailer === p.key ? 'active' : ''}`}
                  onClick={() => setSelectedRetailer(p.key)}
                >
                  {p.name}
                </button>
              ))}
            </div>

            <div className="filter-group">
              <span className="filter-label">Filter:</span>
              <button
                className={`filter-pill ${matchFilter === 'all' ? 'active' : ''}`}
                onClick={() => setMatchFilter('all')}
              >
                All Matches
              </button>
              <button
                className={`filter-pill ${matchFilter === 'exact' ? 'active' : ''}`}
                onClick={() => setMatchFilter('exact')}
              >
                Exact Only
              </button>
              <button
                className={`filter-pill ${matchFilter === 'similar' ? 'active' : ''}`}
                onClick={() => setMatchFilter('similar')}
              >
                Similar Only
              </button>
              <button
                className={`filter-pill ${stockFilter === 'in_stock' ? 'active' : ''}`}
                onClick={() => setStockFilter(stockFilter === 'in_stock' ? 'all' : 'in_stock')}
              >
                {stockFilter === 'in_stock' ? '✓ In Stock Only' : 'In Stock Only'}
              </button>
            </div>

            <div className="filter-group">
              <span className="filter-label">Sort By:</span>
              <select
                className="sort-select"
                value={sortBy}
                onChange={e => setSortBy(e.target.value as any)}
              >
                <option value="price_asc">Lowest Price First</option>
                <option value="discount_desc">Highest Discount First</option>
                <option value="recent">Most Recently Checked</option>
              </select>
            </div>
          </section>

          {/* SECTION: VERIFIED EXACT MATCHES (Clean Product Cards) */}
          {(matchFilter === 'all' || matchFilter === 'exact') && (
            <section className="section">
              <div className="section-heading">
                <div>
                  <div className="eyebrow">VERIFIED EXACT MATCHES</div>
                  <h2>Identified Comparable Listings</h2>
                </div>
                <span className="muted">{filteredExactOffers.length} Verified Listing(s)</span>
              </div>

              {filteredExactOffers.length === 0 ? (
                <div className="empty-chart" style={{ padding: '24px', background: '#fff', borderRadius: '12px' }}>
                  No exact matches found matching the current filters.
                </div>
              ) : (
                <div className="product-cards-grid">
                  {filteredExactOffers.map(offer => {
                    const isOOS = offer.availability?.toLowerCase() === 'out_of_stock'
                    const isUnknown = offer.availability?.toLowerCase() === 'unknown'
                    return (
                      <article className={`enhanced-card ${isOOS ? 'out-of-stock' : ''}`} key={`${offer.platform}:${offer.url}`}>
                        <div className="card-top-bar">
                          <span className="retailer-badge">
                            🛍️ {platformNames[offer.platform] ?? offer.platform}
                          </span>
                          <span className="match-tag exact">✓ Exact Match</span>
                        </div>

                        <div className={`card-media ${isOOS ? 'out-of-stock' : ''}`}>
                          {offer.image_url ? (
                            <img
                            src={offer.image_url}
                            alt={offer.title}
                            loading="lazy"
                            referrerPolicy="no-referrer"
                            onError={(e) => {
                              (e.currentTarget as HTMLElement).style.display = 'none';
                              const p = (e.currentTarget as HTMLElement).parentElement;
                              if (p && !p.querySelector('.fallback-box')) {
                                const fb = document.createElement('div');
                                fb.className = 'fallback-box';
                                fb.style.fontSize = '36px';
                                fb.style.color = '#c4d6cd';
                                fb.textContent = '📦';
                                p.appendChild(fb);
                              }
                            }}
                          />
                          ) : (
                            <div style={{ fontSize: '36px', color: '#c4d6cd' }}>📦</div>
                          )}
                        </div>

                        <div className="card-body">
                          <h3 className="card-title" title={offer.title}>
                            {offer.title}
                          </h3>

                          <div className="card-pricing">
                            <span className="selling-price">{money(offer.price, offer.currency)}</span>
                            {offer.mrp && Number(offer.mrp) > Number(offer.price) && (
                              <span className="mrp-strikethrough">{money(offer.mrp, offer.currency)}</span>
                            )}
                            {offer.discount_percent && Number(offer.discount_percent) > 0 && (
                              <span className="discount-pill">-{offer.discount_percent}% OFF</span>
                            )}
                          </div>

                          <div style={{ marginBottom: '8px' }}>
                            <span
                              className={`availability ${offer.availability} ${isOOS ? 'badge-out-of-stock' : ''}`}
                            >
                              {isOOS
                                ? '● Out of Stock'
                                : isUnknown
                                ? '○ Availability Unknown'
                                : '✓ In Stock'}
                            </span>
                          </div>

                          <div className="match-reason">
                            {Array.isArray(offer.match?.evidence) && offer.match.evidence.length > 0
                              ? `Verification: ${offer.match.evidence.join(', ')}`
                              : 'Exact product and variant match verified.'}
                          </div>

                          <div className="card-footer">
                            <small style={{ fontSize: '10px', color: '#889b91' }}>
                              Checked {time(offer.observed_at)}
                            </small>
                            <div style={{ display: 'flex', gap: '8px' }}>
                              <button
                                className="btn-set-alert"
                                onClick={() => openAlertModal(offer.listing_id || undefined, offer.title)}
                              >
                                🔔 Set Alert
                              </button>
                              <a
                                className="btn-open-retailer"
                                href={offer.url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                View ↗
                              </a>
                            </div>
                          </div>
                        </div>
                      </article>
                    )
                  })}
                </div>
              )}
            </section>
          )}

          {/* SECTION: SIMILAR PRODUCTS (Comparable Alternatives) */}
          {(matchFilter === 'all' || matchFilter === 'similar') && filteredSimilarCandidates.length > 0 && (
            <section className="section similar-section">
              <div className="section-heading">
                <div>
                  <div className="eyebrow">SEPARATE FROM PRICE RANKING</div>
                  <h2>Similar Products & Alternatives</h2>
                </div>
                <span className="muted">
                  Max 3 per retailer | Excluded from lowest-price determination
                </span>
              </div>

              <div className="product-cards-grid">
                {filteredSimilarCandidates.map(candidate => {
                  const isOOS = candidate.availability?.toLowerCase() === 'out_of_stock'
                  const isUnknown = candidate.availability?.toLowerCase() === 'unknown'
                  return (
                    <article className={`enhanced-card ${isOOS ? 'out-of-stock' : ''}`} key={`${candidate.platform}:${candidate.url}`}>
                      <div className="card-top-bar">
                        <span className="retailer-badge">
                          🛍️ {platformNames[candidate.platform] ?? candidate.platform}
                        </span>
                        <span className="match-tag similar">◇ Similar Alternative</span>
                      </div>

                      <div className={`card-media ${isOOS ? 'out-of-stock' : ''}`}>
                        {candidate.image_url ? (
                          <img
                          src={candidate.image_url}
                          alt={candidate.title}
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          onError={(e) => {
                            (e.currentTarget as HTMLElement).style.display = 'none';
                            const p = (e.currentTarget as HTMLElement).parentElement;
                            if (p && !p.querySelector('.fallback-box')) {
                              const fb = document.createElement('div');
                              fb.className = 'fallback-box';
                              fb.style.fontSize = '36px';
                              fb.style.color = '#c4d6cd';
                              fb.textContent = '📦';
                              p.appendChild(fb);
                            }
                          }}
                        />
                        ) : (
                          <div style={{ fontSize: '36px', color: '#c4d6cd' }}>📦</div>
                        )}
                      </div>

                      <div className="card-body">
                        <h3 className="card-title" title={candidate.title}>
                          {candidate.title}
                        </h3>

                        <div className="card-pricing">
                          <span className="selling-price">{money(candidate.price, candidate.currency)}</span>
                          {candidate.mrp && Number(candidate.mrp) > Number(candidate.price) && (
                            <span className="mrp-strikethrough">{money(candidate.mrp, candidate.currency)}</span>
                          )}
                          {candidate.discount_percent && Number(candidate.discount_percent) > 0 && (
                            <span className="discount-pill">-{candidate.discount_percent}% OFF</span>
                          )}
                        </div>

                        <div style={{ marginBottom: '8px' }}>
                          <span
                            className={`availability ${candidate.availability} ${isOOS ? 'badge-out-of-stock' : ''}`}
                          >
                            {isOOS ? '● Out of Stock' : isUnknown ? '○ Availability Unknown' : '✓ In Stock'}
                          </span>
                        </div>

                        <div className="match-reason">
                          {Array.isArray(candidate.match_evidence?.conflicts) && candidate.match_evidence.conflicts.length > 0
                            ? `Differs: ${candidate.match_evidence.conflicts.join(', ')}`
                            : Array.isArray(candidate.match_evidence?.missing) && candidate.match_evidence.missing.length > 0
                            ? `Unverified: ${candidate.match_evidence.missing.join(', ')}`
                            : 'Comparable alternative model.'}
                        </div>

                        <div className="card-footer">
                          <small style={{ fontSize: '10px', color: '#889b91' }}>
                            Checked {time(candidate.observed_at)}
                          </small>
                          <a
                            className="btn-open-retailer"
                            href={candidate.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            View Alternative ↗
                          </a>
                        </div>
                      </div>
                    </article>
                  )
                })}
              </div>
            </section>
          )}

          {/* LOWER SECTION: PRICE MONITORING GRAPH & ACTIVE ALERTS */}
          <section className="result-grid lower-grid">
            {/* Price History Chart with Target Lines */}
            <article className="history-card">
              <div className="section-heading">
                <div>
                  <div className="eyebrow">MONITORING GRAPH</div>
                  <h3>Price History & Alert Thresholds</h3>
                </div>
                <span className="muted">{chartData?.count || 0} observations</span>
              </div>

              {chartData ? (
                <div>
                  <div className="chart-container">
                    <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Price history graph with alert thresholds" style={{ width: '100%', height: '100%' }}>
                      {/* Grid line */}
                      <line x1="0" y1="90" x2="100" y2="90" stroke="#e0ece5" strokeWidth="1" />
                      {/* Historical observations line */}
                      {chartData.points ? (
                        <polyline points={chartData.points} fill="none" stroke="#247b5c" strokeWidth="2" strokeLinecap="round" />
                      ) : null}
                      {/* Active target alert lines */}
                      {(chartData.activeTargets ?? []).map((t, idx) => (
                        <g key={idx}>
                          <line x1="0" y1={t.y} x2="100" y2={t.y} className="threshold-line" />
                          <text x="2" y={t.y - 2} className="threshold-label">
                            Target {money(t.target, 'INR')}
                          </text>
                        </g>
                      ))}
                    </svg>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#7a8c83', marginTop: '6px' }}>
                    <span>Min: {money(chartData.minPrice, 'INR')}</span>
                    <span>Max: {money(chartData.maxPrice, 'INR')}</span>
                  </div>
                </div>
              ) : (
                <div className="empty-chart">Price history and threshold lines will appear as observations accumulate.</div>
              )}
            </article>

            {/* Active Alerts for this Product */}
            <article className="tracking-card">
              <div className="section-heading">
                <div>
                  <div className="eyebrow">ACTIVE ALERTS</div>
                  <h3>Monitored on this Product</h3>
                </div>
                <button className="btn-set-alert" onClick={() => openAlertModal()}>
                  + Add Alert
                </button>
              </div>

              {activeAlertsForProduct.length === 0 ? (
                <p style={{ fontSize: '12px', color: '#778a81', margin: '14px 0' }}>
                  No active alerts for this product yet. Click "+ Add Alert" or "Set Alert" on any offer card.
                </p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '12px' }}>
                  {activeAlertsForProduct.map(job => (
                    <div
                      key={job.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '10px 12px',
                        background: '#f8faf9',
                        borderRadius: '8px',
                        border: '1px solid #e2ece6',
                      }}
                    >
                      <div>
                        <div style={{ fontSize: '12px', fontWeight: 700, color: '#1d4d3c' }}>
                          {job.name || `${job.mode.replace('_', ' ').toUpperCase()} ALERT`}
                        </div>
                        <div style={{ fontSize: '10px', color: '#688075', marginTop: '2px' }}>
                          {job.mode === 'target_price' && `Target: ${money(job.target_price, 'INR')}`}
                          {job.mode === 'percent_drop' && `Drop: >= ${job.threshold_percent}%`}
                          {job.mode === 'any_drop' && 'Any price drop'}
                          {job.mode === 'back_in_stock' && 'Triggers when back in stock'}
                          {job.mode === 'out_of_stock' && 'Triggers when out of stock'}
                          {job.mode === 'price_change' && 'Triggers on any price change'}
                          {' · '}Interval: {job.interval_minutes}m
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <button
                          className="text-button"
                          style={{ fontSize: '11px', color: job.active ? '#a85b3b' : '#2b8264' }}
                          onClick={() => toggleTrackingJob(job.id, job.active)}
                        >
                          {job.active ? 'Pause' : 'Resume'}
                        </button>
                        <button
                          className="text-button"
                          style={{ fontSize: '11px', color: '#a33d3d' }}
                          onClick={() => removeTrackingJob(job.id)}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </article>
          </section>
        </>
        )
      })()}

      {/* TAB 2: DEDICATED DATA & CALCULATIONS PAGE */}
      {activeTab === 'data-calc' && (
        <section className="data-calc-container">
          <div className="hero" style={{ padding: '24px 0 12px' }}>
            <div className="eyebrow">SYSTEM TRANSPARENCY & EVIDENCE AUDIT</div>
            <h1>Data & Calculations</h1>
            <p>
              Exhaustive live telemetry on data sources, extraction mechanisms, product verification, price calculations, and alert evaluation engine.
            </p>
          </div>

          {/* Section A: Data Sources */}
          <div className="calc-section">
            <div className="calc-header">
              <span className="section-tag">Section A</span>
              <h2>Data Sources</h2>
              <p>Aggregated entity counts stored in the verified database.</p>
            </div>
            <div className="metric-grid">
              <div className="metric-box">
                <div className="metric-val">{dataCalc?.data_sources.total_products ?? '—'}</div>
                <div className="metric-title">Unique Products Tracked</div>
                <div className="metric-sub">Catalog entities</div>
              </div>
              <div className="metric-box">
                <div className="metric-val">{dataCalc?.data_sources.total_listings ?? '—'}</div>
                <div className="metric-title">Retailer Listings</div>
                <div className="metric-sub">Across 7 Indian retailers</div>
              </div>
              <div className="metric-box">
                <div className="metric-val">{dataCalc?.data_sources.total_price_observations ?? '—'}</div>
                <div className="metric-title">Price Observations</div>
                <div className="metric-sub">Historical recorded prices</div>
              </div>
              <div className="metric-box">
                <div className="metric-val">{dataCalc?.data_sources.total_stock_observations ?? '—'}</div>
                <div className="metric-title">Stock Observations</div>
                <div className="metric-sub">Inventory state points</div>
              </div>
              <div className="metric-box">
                <div className="metric-val">{dataCalc?.data_sources.active_tracking_jobs ?? '—'}</div>
                <div className="metric-title">Active Alert Jobs</div>
                <div className="metric-sub">Scheduled background checks</div>
              </div>
              <div className="metric-box">
                <div className="metric-val">{dataCalc?.data_sources.total_discovery_runs ?? '—'}</div>
                <div className="metric-title">Discovery Runs</div>
                <div className="metric-sub">Completed multi-platform searches</div>
              </div>
            </div>
          </div>

          {/* Section B: Data Extraction */}
          <div className="calc-section">
            <div className="calc-header">
              <span className="section-tag">Section B</span>
              <h2>Data Extraction Breakdown</h2>
              <p>Reliable extraction distribution from structured data, DOM selectors, and embedded scripts.</p>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
              <div>
                <h4 style={{ margin: '0 0 10px', fontSize: '13px', color: '#1f4435' }}>Price Extraction Sources</h4>
                <div className="metric-box">
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #eef3f0' }}>
                    <span>JSON-LD Structured Data</span>
                    <b>{dataCalc?.data_extraction.sources.json_ld ?? 0}</b>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #eef3f0' }}>
                    <span>HTML Selectors (Retailer PDP)</span>
                    <b>{dataCalc?.data_extraction.sources.html_selectors ?? 0}</b>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                    <span>Embedded State Scripts (myx, INITIAL_STATE)</span>
                    <b>{dataCalc?.data_extraction.sources.embedded_scripts ?? 0}</b>
                  </div>
                </div>
              </div>

              <div>
                <h4 style={{ margin: '0 0 10px', fontSize: '13px', color: '#1f4435' }}>Stock Availability Distribution</h4>
                <div className="distribution-bar">
                  <div
                    className="dist-segment"
                    style={{
                      width: `${((dataCalc?.data_extraction.stock_distribution.in_stock || 0) / (dataCalc?.data_sources.total_price_observations || 1)) * 100}%`,
                      background: '#2ba871',
                    }}
                    title="In Stock"
                  />
                  <div
                    className="dist-segment"
                    style={{
                      width: `${((dataCalc?.data_extraction.stock_distribution.out_of_stock || 0) / (dataCalc?.data_sources.total_price_observations || 1)) * 100}%`,
                      background: '#d45647',
                    }}
                    title="Out of Stock"
                  />
                  <div
                    className="dist-segment"
                    style={{
                      width: `${((dataCalc?.data_extraction.stock_distribution.unknown || 0) / (dataCalc?.data_sources.total_price_observations || 1)) * 100}%`,
                      background: '#b0bfb8',
                    }}
                    title="Unknown"
                  />
                </div>
                <div className="dist-legend">
                  <div className="legend-item">
                    <span className="legend-dot" style={{ background: '#2ba871' }} />
                    <span>In Stock: {dataCalc?.data_extraction.stock_distribution.in_stock ?? 0}</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-dot" style={{ background: '#d45647' }} />
                    <span>Out of Stock: {dataCalc?.data_extraction.stock_distribution.out_of_stock ?? 0}</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-dot" style={{ background: '#b0bfb8' }} />
                    <span>Unknown: {dataCalc?.data_extraction.stock_distribution.unknown ?? 0}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Section C: Matching & Verification */}
          <div className="calc-section">
            <div className="calc-header">
              <span className="section-tag">Section C</span>
              <h2>Matching and Verification Engine</h2>
              <p>Bi-directional token matching and strict critical specifications enforcement.</p>
            </div>
            <div className="metric-grid" style={{ marginBottom: '14px' }}>
              <div className="metric-box">
                <div className="metric-val">{dataCalc?.matching_verification.exact_matches_found ?? 0}</div>
                <div className="metric-title">Verified Exact Candidates</div>
                <div className="metric-sub">Passed all critical spec rules</div>
              </div>
              <div className="metric-box">
                <div className="metric-val">{dataCalc?.matching_verification.similar_matches_found ?? 0}</div>
                <div className="metric-title">Similar / Probable Candidates</div>
                <div className="metric-sub">Separate from price rankings</div>
              </div>
            </div>
            <h4 style={{ margin: '14px 0 6px', fontSize: '12px', color: '#3d5c4e' }}>
              Active Critical Spec Verification Rules:
            </h4>
            <div className="tags-cloud">
              {dataCalc?.matching_verification.critical_spec_rules.map(rule => (
                <span className="rule-tag" key={rule}>
                  {rule}
                </span>
              ))}
            </div>
          </div>

          {/* Section D: Price Calculations */}
          <div className="calc-section">
            <div className="calc-header">
              <span className="section-tag">Section D</span>
              <h2>Price Calculations & Methodology</h2>
              <p>How selling prices, MRP discounts, and lowest verified offers are mathematically derived.</p>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
              <div className="metric-box">
                <b style={{ color: '#1b4b38', fontSize: '13px' }}>MRP Discount Formula</b>
                <pre style={{ background: '#edf4f0', padding: '10px', borderRadius: '6px', fontSize: '11px', margin: '8px 0' }}>
                  {dataCalc?.price_calculations.formula_mrp_discount}
                </pre>
                <small style={{ color: '#688075' }}>
                  Calculated whenever positive evidence of both selling price and list price (MRP) is extracted.
                </small>
              </div>
              <div className="metric-box">
                <b style={{ color: '#1b4b38', fontSize: '13px' }}>Lowest Price Qualification Rules</b>
                <p style={{ fontSize: '11px', color: '#556d61', margin: '8px 0' }}>
                  {dataCalc?.price_calculations.lowest_verified_price_rules}
                </p>
                <small style={{ color: '#688075' }}>
                  Similar products, unverified listings, and stale observations (&gt;24h) are disqualified.
                </small>
              </div>
              <div className="metric-box">
                <b style={{ color: '#1b4b38', fontSize: '13px' }}>Maximum Discount Observed</b>
                <div style={{ fontSize: '24px', fontWeight: 800, color: '#186445', margin: '8px 0' }}>
                  {dataCalc?.price_calculations.max_discount_observed_pct}%
                </div>
                <small style={{ color: '#688075' }}>Peak verified discount across Indian platforms.</small>
              </div>
            </div>
          </div>

          {/* Section E: Alert Evaluation Engine */}
          <div className="calc-section">
            <div className="calc-header">
              <span className="section-tag">Section E</span>
              <h2>Alert Evaluation Engine</h2>
              <p>Real-time background scheduler comparing fresh observations against configured alert rules.</p>
            </div>
            <div className="metric-grid">
              <div className="metric-box">
                <div className="metric-val">{dataCalc?.alert_evaluation.total_alert_events ?? 0}</div>
                <div className="metric-title">Triggered Alert Events</div>
                <div className="metric-sub">Historical notifications</div>
              </div>
              <div className="metric-box">
                <div className="metric-val">
                  {Object.keys(dataCalc?.alert_evaluation.mode_distribution || {}).length}
                </div>
                <div className="metric-title">Active Alert Types</div>
                <div className="metric-sub">target_price, percent_drop, stock</div>
              </div>
              <div className="metric-box">
                <div style={{ fontSize: '13px', fontWeight: 700, color: '#1b4b38' }}>
                  {time(dataCalc?.alert_evaluation.next_scheduled_check)}
                </div>
                <div className="metric-title">Next Scheduled Check</div>
                <div className="metric-sub">APScheduler background cycle</div>
              </div>
            </div>
          </div>

          {/* Section F: Retailer Operational Status & Health */}
          <div className="calc-section">
            <div className="calc-header">
              <span className="section-tag">Section F</span>
              <h2>Per-Retailer Health & Recent Telemetry</h2>
              <p>Operational status across all seven Indian shopping platforms.</p>
            </div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Retailer</th>
                  <th>Tracked Listings</th>
                  <th>Discovered Candidates</th>
                  <th>Operational Status</th>
                </tr>
              </thead>
              <tbody>
                {(dataCalc?.job_activity.retailers || []).map(r => (
                  <tr key={r.key}>
                    <td>
                      <b>{r.name}</b>
                    </td>
                    <td>{r.listings_tracked}</td>
                    <td>{r.candidates_discovered}</td>
                    <td>
                      <span style={{ color: '#27855e', fontWeight: 600 }}>● {r.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h4 style={{ margin: '20px 0 8px', fontSize: '13px', color: '#1c4233' }}>
              Recent Extraction Activity (Last 10 Events)
            </h4>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Platform</th>
                  <th>Price</th>
                  <th>Stock</th>
                  <th>Source</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {(dataCalc?.job_activity.recent_activity || []).map(act => (
                  <tr key={act.id}>
                    <td>{time(act.observed_at)}</td>
                    <td>{platformNames[act.platform] ?? act.platform}</td>
                    <td>{money(act.price, act.currency)}</td>
                    <td>
                      <span className={`availability ${act.availability}`}>{act.availability.replace('_', ' ')}</span>
                    </td>
                    <td>{act.source}</td>
                    <td>{act.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* TAB 3: SAVED ALERTS & TRACKING */}
      {activeTab === 'alerts' && (
        <section className="data-calc-container">
          <div className="hero" style={{ padding: '24px 0 12px' }}>
            <div className="eyebrow">ACTIVE MONITORING</div>
            <h1>Saved Price & Stock Alerts</h1>
            <p>Manage all independent alerts across products and view alert trigger event logs.</p>
          </div>

          <div className="calc-section">
            <div className="calc-header">
              <h2>Configured Monitoring Jobs ({trackingJobs.length})</h2>
            </div>

            {trackingJobs.length === 0 ? (
              <p style={{ fontSize: '12px', color: '#688075' }}>
                No tracking jobs configured yet. Search for a product and enable an alert.
              </p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Alert Name</th>
                    <th>Product</th>
                    <th>Mode</th>
                    <th>Threshold</th>
                    <th>Interval</th>
                    <th>Last Check</th>
                    <th>Next Check</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {trackingJobs.map(job => (
                    <tr key={job.id}>
                      <td>
                        <b>{job.name || `${job.mode.replace('_', ' ')} Alert`}</b>
                      </td>
                      <td style={{ maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {job.product_title || 'Product'}
                      </td>
                      <td>
                        <span style={{ textTransform: 'capitalize' }}>{job.mode.replace('_', ' ')}</span>
                      </td>
                      <td>
                        {job.mode === 'target_price' && money(job.target_price, 'INR')}
                        {job.mode === 'percent_drop' && `>= ${job.threshold_percent}%`}
                        {job.mode === 'any_drop' && 'Any Drop'}
                        {job.mode === 'back_in_stock' && 'Stock Arrival'}
                        {job.mode === 'out_of_stock' && 'Stock Out'}
                        {job.mode === 'price_change' && 'Any Change'}
                      </td>
                      <td>{job.interval_minutes}m</td>
                      <td>{time(job.last_checked_at)}</td>
                      <td>{time(job.next_run_at)}</td>
                      <td>
                        <span style={{ color: job.active ? '#25805c' : '#8c9c94', fontWeight: 600 }}>
                          {job.active ? 'Active' : 'Paused'}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: '8px' }}>
                          <button
                            className="text-button"
                            style={{ color: job.active ? '#a85b3b' : '#2b8264' }}
                            onClick={() => toggleTrackingJob(job.id, job.active)}
                          >
                            {job.active ? 'Pause' : 'Resume'}
                          </button>
                          <button
                            className="text-button"
                            style={{ color: '#a33d3d' }}
                            onClick={() => removeTrackingJob(job.id)}
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Triggered Alert Events Log */}
          <div className="calc-section">
            <div className="calc-header">
              <h2>Triggered Alert History ({alerts.length})</h2>
              <p>Events fired when verified price or availability matched an active alert condition.</p>
            </div>
            {alerts.length === 0 ? (
              <p style={{ fontSize: '12px', color: '#688075' }}>No alert events have triggered yet.</p>
            ) : (
              <div className="alert-list">
                {alerts.map(alert => (
                  <article className="alert-event" key={alert.id}>
                    <span className="alert-icon">
                      {alert.kind.includes('stock') ? '📦' : '₹'}
                    </span>
                    <div>
                      <b>{alert.kind.replace('_', ' ').toUpperCase()}</b>
                      <p>{alert.message}</p>
                    </div>
                    <time>{time(alert.created_at)}</time>
                  </article>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {/* ALERT MODAL / DRAWER */}
      {alertModalOpen && (
        <div className="modal-backdrop" onClick={() => setAlertModalOpen(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3>Configure Price & Stock Alert</h3>
                <p title={alertTargetListingTitle} style={{ maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {alertTargetListingTitle}
                </p>
              </div>
              <button className="btn-close" onClick={() => setAlertModalOpen(false)}>
                ✕
              </button>
            </div>

            <form onSubmit={saveAlert}>
              <div className="form-group">
                <label htmlFor="alert-mode-select">Alert Type</label>
                <select
                  id="alert-mode-select"
                  className="form-select"
                  value={alertMode}
                  onChange={e => setAlertMode(e.target.value as any)}
                >
                  <option value="any_drop">Any Price Drop (notify on decrease)</option>
                  <option value="target_price">Target Price (notify when &le; target INR)</option>
                  <option value="percent_drop">Percentage Drop (e.g. drops by 10%+)</option>
                  <option value="back_in_stock">Back in Stock (notify when inventory returns)</option>
                  <option value="out_of_stock">Out of Stock (notify when sold out)</option>
                  <option value="price_change">Price Change (notify on any fluctuation)</option>
                </select>
              </div>

              {alertMode === 'target_price' && (
                <div className="form-group">
                  <label htmlFor="modal-target-price">Target Price (INR)</label>
                  <input
                    id="modal-target-price"
                    className="form-input"
                    type="number"
                    step="0.01"
                    min="1"
                    required
                    placeholder="e.g. 45000"
                    value={alertTargetPrice}
                    onChange={e => setAlertTargetPrice(e.target.value)}
                  />
                </div>
              )}

              {alertMode === 'percent_drop' && (
                <div className="form-group">
                  <label htmlFor="modal-threshold-percent">Minimum Drop Percentage (%)</label>
                  <input
                    id="modal-threshold-percent"
                    className="form-input"
                    type="number"
                    step="0.5"
                    min="1"
                    max="90"
                    required
                    placeholder="e.g. 10"
                    value={alertThresholdPercent}
                    onChange={e => setAlertThresholdPercent(e.target.value)}
                  />
                </div>
              )}

              <div className="form-group">
                <label htmlFor="modal-interval">Check Frequency</label>
                <select
                  id="modal-interval"
                  className="form-select"
                  value={alertInterval}
                  onChange={e => setAlertInterval(Number(e.target.value))}
                >
                  <option value="15">Every 15 minutes</option>
                  <option value="30">Every 30 minutes</option>
                  <option value="60">Every 1 hour</option>
                  <option value="360">Every 6 hours</option>
                  <option value="720">Every 12 hours</option>
                  <option value="1440">Daily (24 hours)</option>
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="modal-alert-name">Alert Label (Optional)</label>
                <input
                  id="modal-alert-name"
                  className="form-input"
                  type="text"
                  placeholder="e.g. Best price drop on Flipkart"
                  value={alertName}
                  onChange={e => setAlertName(e.target.value)}
                />
              </div>

              <div className="modal-actions">
                <button type="button" className="btn-secondary" onClick={() => setAlertModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={alertBusy}>
                  {alertBusy ? 'Saving...' : 'Activate Alert'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* TAB 4: USER ACCOUNT & MY ALERTS */}
      {activeTab === 'account' && (
        <UserAccountSection
          onSignOut={handleSignOut}
          onInspectProduct={(inspUrl) => {
            setUrl(inspUrl)
            setActiveTab('compare')
            inspectProduct(inspUrl)
              .then(setComparison)
              .catch(err => setError(err.message || 'Inspection failed'))
          }}
        />
      )}

      {/* Auth Modal */}
      <AuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        onSuccess={(u) => {
          setCurrentUser(u)
          setAuthModalOpen(false)
        }}
      />

      {/* Price History Chart Modal */}
      {comparison?.product && (
        <PriceHistoryChart
          productId={comparison.product.id}
          productTitle={comparison.product.title}
          isOpen={historyChartOpen}
          onClose={() => setHistoryChartOpen(false)}
        />
      )}

      {/* Footer */}
      <footer>
        <span>PriceTruth AI</span>
        <span>Evidence-first Indian price comparison. Prices verified from genuine retailer pages.</span>
      </footer>
    </main>
  )
}
