import React, { useState, useEffect } from 'react'
import { getProductPriceHistory } from '../lib/api'
import type { PriceHistoryResponse } from '../types'

interface PriceHistoryChartProps {
  productId: number
  productTitle?: string
  isOpen: boolean
  onClose: () => void
}

const RANGES = [
  { label: '24 Hours', value: '24h' },
  { label: '7 Days', value: '7d' },
  { label: '30 Days', value: '30d' },
  { label: '90 Days', value: '90d' },
  { label: 'All Time', value: 'all' },
]

export const PriceHistoryChart: React.FC<PriceHistoryChartProps> = ({
  productId,
  productTitle,
  isOpen,
  onClose,
}) => {
  const [range, setRange] = useState('30d')
  const [data, setData] = useState<PriceHistoryResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hoveredPoint, setHoveredPoint] = useState<any | null>(null)

  useEffect(() => {
    if (!isOpen || !productId) return
    setLoading(true)
    setError(null)
    getProductPriceHistory(productId, range)
      .then((res) => setData(res))
      .catch((err) => setError(err.message || 'Failed to load price history'))
      .finally(() => setLoading(false))
  }, [productId, range, isOpen])

  if (!isOpen) return null

  const points = data?.points || []
  const summary = data?.summary

  // SVG Chart Dimensions
  const width = 640
  const height = 240
  const padding = { top: 20, right: 30, bottom: 40, left: 65 }
  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom

  const minPrice = summary?.min_price ?? 0
  const maxPrice = summary?.max_price ?? 0
  const priceRange = maxPrice - minPrice === 0 ? 1 : maxPrice - minPrice

  // Generate SVG coordinates
  const svgPoints = points.map((pt, idx) => {
    const x =
      points.length === 1
        ? padding.left + chartWidth / 2
        : padding.left + (idx / (points.length - 1)) * chartWidth
    const y =
      padding.top +
      chartHeight -
      ((pt.price - minPrice) / priceRange) * chartHeight
    return { ...pt, x, y }
  })

  const pathD =
    svgPoints.length > 1
      ? svgPoints.reduce(
          (acc, pt, i) => `${acc} ${i === 0 ? 'M' : 'L'} ${pt.x} ${pt.y}`,
          ''
        )
      : ''

  const formatINR = (val?: number | null) =>
    val !== undefined && val !== null
      ? '₹' + Math.round(val).toLocaleString('en-IN')
      : '—'

  return (
    <div
      className="modal-backdrop"
      onClick={onClose}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(15, 23, 42, 0.75)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
        padding: '16px',
      }}
    >
      <div
        className="history-modal"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#ffffff',
          borderRadius: '16px',
          width: '100%',
          maxWidth: '700px',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
          overflow: 'hidden',
          border: '1px solid #e2e8f0',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '20px 24px',
            borderBottom: '1px solid #f1f5f9',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span
                style={{
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  padding: '3px 8px',
                  borderRadius: '6px',
                  background: '#eff6ff',
                  color: '#2563eb',
                }}
              >
                Price History
              </span>
              <span style={{ fontSize: '0.85rem', color: '#64748b' }}>
                Verified observations
              </span>
            </div>
            <h3
              style={{
                margin: '6px 0 0',
                fontSize: '1.15rem',
                fontWeight: 700,
                color: '#0f172a',
                lineHeight: 1.3,
              }}
            >
              {productTitle || `Product #${productId}`}
            </h3>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              fontSize: '1.5rem',
              color: '#94a3b8',
              cursor: 'pointer',
              lineHeight: 1,
              padding: '4px',
            }}
          >
            ×
          </button>
        </div>

        {/* Range selectors and stats bar */}
        <div
          style={{
            padding: '16px 24px',
            background: '#f8fafc',
            borderBottom: '1px solid #e2e8f0',
            display: 'flex',
            flexWrap: 'wrap',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '12px',
          }}
        >
          {/* Summary stats */}
          <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: '0.7rem', color: '#64748b', textTransform: 'uppercase' }}>Current</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#0f172a' }}>
                {formatINR(summary?.current_price)}
              </div>
            </div>
            <div style={{ height: '24px', width: '1px', background: '#cbd5e1' }} />
            <div>
              <div style={{ fontSize: '0.7rem', color: '#64748b', textTransform: 'uppercase' }}>Lowest</div>
              <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#16a34a' }}>
                {formatINR(summary?.min_price)}
              </div>
            </div>
            <div style={{ height: '24px', width: '1px', background: '#cbd5e1' }} />
            <div>
              <div style={{ fontSize: '0.7rem', color: '#64748b', textTransform: 'uppercase' }}>Highest</div>
              <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#dc2626' }}>
                {formatINR(summary?.max_price)}
              </div>
            </div>
          </div>

          {/* Range buttons */}
          <div
            style={{
              display: 'flex',
              background: '#e2e8f0',
              borderRadius: '8px',
              padding: '3px',
              gap: '2px',
            }}
          >
            {RANGES.map((r) => (
              <button
                key={r.value}
                onClick={() => setRange(r.value)}
                style={{
                  border: 'none',
                  padding: '6px 12px',
                  borderRadius: '6px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  background: range === r.value ? '#ffffff' : 'transparent',
                  color: range === r.value ? '#0f172a' : '#64748b',
                  boxShadow: range === r.value ? '0 1px 2px rgba(0,0,0,0.05)' : 'none',
                }}
              >
                {r.value.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        {/* Chart Canvas */}
        <div style={{ padding: '24px', position: 'relative' }}>
          {loading ? (
            <div
              style={{
                height: height,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#64748b',
              }}
            >
              Loading verified price observations...
            </div>
          ) : error ? (
            <div
              style={{
                height: height,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#dc2626',
              }}
            >
              {error}
            </div>
          ) : points.length === 0 ? (
            <div
              style={{
                height: height,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#64748b',
                gap: '8px',
              }}
            >
              <div>No price observations recorded for this {range} window.</div>
              <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                Trigger an inspection or refresh to log observations.
              </div>
            </div>
          ) : (
            <div>
              <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
                {/* Horizontal Grid lines */}
                {[0, 0.25, 0.5, 0.75, 1].map((pct) => {
                  const y = padding.top + chartHeight * (1 - pct)
                  const priceTick = minPrice + priceRange * pct
                  return (
                    <g key={pct}>
                      <line
                        x1={padding.left}
                        y1={y}
                        x2={width - padding.right}
                        y2={y}
                        stroke="#f1f5f9"
                        strokeWidth="1"
                        strokeDasharray={pct === 0 || pct === 1 ? 'none' : '4 4'}
                      />
                      <text
                        x={padding.left - 8}
                        y={y + 4}
                        textAnchor="end"
                        fontSize="10"
                        fill="#94a3b8"
                        fontFamily="sans-serif"
                      >
                        {formatINR(priceTick)}
                      </text>
                    </g>
                  )
                })}

                {/* Shaded Area under line */}
                {svgPoints.length > 1 && (
                  <path
                    d={`${pathD} L ${svgPoints[svgPoints.length - 1].x} ${
                      padding.top + chartHeight
                    } L ${svgPoints[0].x} ${padding.top + chartHeight} Z`}
                    fill="url(#chartGradient)"
                    opacity="0.15"
                  />
                )}

                {/* Gradient Def */}
                <defs>
                  <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#2563eb" />
                    <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
                  </linearGradient>
                </defs>

                {/* Line Path */}
                {pathD && (
                  <path
                    d={pathD}
                    fill="none"
                    stroke="#2563eb"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                )}

                {/* Points */}
                {svgPoints.map((pt, i) => (
                  <circle
                    key={i}
                    cx={pt.x}
                    cy={pt.y}
                    r={hoveredPoint?.id === pt.id ? 6 : 4}
                    fill={hoveredPoint?.id === pt.id ? '#1d4ed8' : '#2563eb'}
                    stroke="#ffffff"
                    strokeWidth="2"
                    style={{ cursor: 'pointer', transition: 'all 0.15s ease' }}
                    onMouseEnter={() => setHoveredPoint(pt)}
                    onMouseLeave={() => setHoveredPoint(null)}
                  />
                ))}
              </svg>

              {/* Tooltip */}
              {hoveredPoint && (
                <div
                  style={{
                    position: 'absolute',
                    top: '30px',
                    right: '30px',
                    background: '#0f172a',
                    color: '#ffffff',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.2)',
                    fontSize: '0.8rem',
                    pointerEvents: 'none',
                    zIndex: 10,
                  }}
                >
                  <div style={{ fontWeight: 700, fontSize: '0.95rem', color: '#60a5fa' }}>
                    {formatINR(hoveredPoint.price)}
                  </div>
                  <div style={{ color: '#cbd5e1', marginTop: '2px' }}>
                    {hoveredPoint.platform}
                  </div>
                  <div style={{ color: '#94a3b8', fontSize: '0.75rem', marginTop: '2px' }}>
                    {new Date(hoveredPoint.observed_at).toLocaleString()}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '12px 24px',
            background: '#f8fafc',
            borderTop: '1px solid #f1f5f9',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: '0.75rem',
            color: '#64748b',
          }}
        >
          <div>Total data points: {points.length}</div>
          <button
            onClick={onClose}
            style={{
              padding: '6px 14px',
              borderRadius: '6px',
              border: '1px solid #cbd5e1',
              background: '#ffffff',
              color: '#334155',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
