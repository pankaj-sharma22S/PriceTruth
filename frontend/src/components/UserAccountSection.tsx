import React, { useState, useEffect } from 'react'
import {
  getUserProfile,
  updateUserProfile,
  getUserAlerts,
  createUserAlert,
  updateUserAlert,
  deleteUserAlert,
  getSavedProducts,
  removeSavedProduct,
  getUserAlertHistory,
  getUserNotifications,
  markNotificationRead,
  markAllNotificationsRead,
} from '../lib/api'
import type {
  PriceAlert,
  SavedProduct,
  UserAlertHistoryEvent,
  UserNotification,
  UserProfile,
} from '../types'
import { PriceHistoryChart } from './PriceHistoryChart'

interface UserAccountSectionProps {
  onSignOut: () => void
  onInspectProduct?: (url: string) => void
}

export const UserAccountSection: React.FC<UserAccountSectionProps> = ({
  onSignOut,
  onInspectProduct,
}) => {
  const [activeTab, setActiveTab] = useState<
    'alerts' | 'saved' | 'history' | 'notifications' | 'settings'
  >('alerts')

  // Data states
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [alerts, setAlerts] = useState<PriceAlert[]>([])
  const [alertFilter, setAlertFilter] = useState<'ALL' | 'ACTIVE' | 'TRIGGERED' | 'PAUSED'>('ALL')
  const [savedProducts, setSavedProducts] = useState<SavedProduct[]>([])
  const [history, setHistory] = useState<UserAlertHistoryEvent[]>([])
  const [notifications, setNotifications] = useState<UserNotification[]>([])
  const [hasUnread, setHasUnread] = useState(false)
  const [loading, setLoading] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)

  // Chart modal state
  const [chartProductId, setChartProductId] = useState<number | null>(null)
  const [chartProductTitle, setChartProductTitle] = useState<string>('')

  // Modal / Dialog states
  const [editingAlert, setEditingAlert] = useState<PriceAlert | null>(null)
  const [newTargetPrice, setNewTargetPrice] = useState<string>('')
  const [deleteConfirmAlertId, setDeleteConfirmAlertId] = useState<number | null>(null)
  const [deleteConfirmProductId, setDeleteConfirmProductId] = useState<number | null>(null)

  // Lower Target Alert modal state
  const [lowerAlertProduct, setLowerAlertProduct] = useState<{ id: number; title: string; currentPrice?: number | null } | null>(null)
  const [lowerTargetInput, setLowerTargetInput] = useState<string>('')

  // Settings form
  const [displayName, setDisplayName] = useState('')
  const [checkInterval, setCheckInterval] = useState('360')

  const formatINR = (val?: number | null) =>
    val !== undefined && val !== null
      ? '₹' + Math.round(val).toLocaleString('en-IN')
      : '—'

  const loadData = async () => {
    setLoading(true)
    try {
      const [prof, alertRes, savedRes, histRes, notifRes] = await Promise.all([
        getUserProfile().catch(() => null),
        getUserAlerts().catch(() => ({ alerts: [] })),
        getSavedProducts().catch(() => ({ saved_products: [] })),
        getUserAlertHistory().catch(() => ({ history: [] })),
        getUserNotifications().catch(() => ({ notifications: [], has_unread: false })),
      ])

      if (prof) {
        setProfile(prof)
        setDisplayName(prof.full_name || '')
      }
      setAlerts(alertRes.alerts || [])
      setSavedProducts(savedRes.saved_products || [])
      setHistory(histRes.history || [])
      setNotifications(notifRes.notifications || [])
      setHasUnread(notifRes.has_unread || false)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  // Action handlers
  const handleTogglePause = async (alertItem: PriceAlert) => {
    const nextStatus = alertItem.status === 'PAUSED' ? 'ACTIVE' : 'PAUSED'
    try {
      await updateUserAlert(alertItem.id, { status: nextStatus })
      setFeedback(`Alert ${nextStatus === 'ACTIVE' ? 'resumed' : 'paused'} successfully.`)
      loadData()
    } catch (err: any) {
      window.alert(err.message || 'Failed to update alert status')
    }
  }

  const handleUpdateTarget = async () => {
    if (!editingAlert) return
    const priceNum = parseFloat(newTargetPrice)
    if (isNaN(priceNum) || priceNum <= 0) {
      window.alert('Please enter a valid target price.')
      return
    }
    try {
      await updateUserAlert(editingAlert.id, { target_price: priceNum, status: 'ACTIVE' })
      setEditingAlert(null)
      setFeedback('Target price updated and alert reactivated.')
      loadData()
    } catch (err: any) {
      window.alert(err.message || 'Failed to update alert target')
    }
  }

  const handleDeleteAlert = async (id: number) => {
    try {
      await deleteUserAlert(id)
      setDeleteConfirmAlertId(null)
      setFeedback('Alert deleted successfully.')
      loadData()
    } catch (err: any) {
      window.alert(err.message || 'Failed to delete alert')
    }
  }

  const handleCreateLowerAlert = async () => {
    if (!lowerAlertProduct) return
    const targetNum = parseFloat(lowerTargetInput)
    if (isNaN(targetNum) || targetNum <= 0) {
      window.alert('Please enter a valid target price.')
      return
    }
    try {
      await createUserAlert({
        product_id: lowerAlertProduct.id,
        mode: 'target_price',
        target_price: targetNum,
        name: `Target ₹${targetNum} for ${lowerAlertProduct.title.slice(0, 30)}`,
        interval_minutes: 360,
      })
      setLowerAlertProduct(null)
      setLowerTargetInput('')
      setFeedback(`New lower target alert created at ₹${targetNum.toLocaleString('en-IN')}.`)
      loadData()
    } catch (err: any) {
      window.alert(err.message || 'Failed to create secondary alert')
    }
  }

  const handleRemoveSaved = async (productId: number) => {
    try {
      await removeSavedProduct(productId)
      setDeleteConfirmProductId(null)
      setFeedback('Product removed from saved items.')
      loadData()
    } catch (err: any) {
      window.alert(err.message || 'Failed to remove saved product')
    }
  }

  const handleMarkNotif = async (id: number) => {
    try {
      await markNotificationRead(id)
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      )
    } catch (e) {}
  }

  const handleMarkAllNotifs = async () => {
    try {
      await markAllNotificationsRead()
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })))
      setHasUnread(false)
    } catch (e) {}
  }

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await updateUserProfile({
        full_name: displayName,
        preferences: { check_interval_minutes: parseInt(checkInterval, 10) },
      })
      setFeedback('Account preferences saved successfully.')
      loadData()
    } catch (err: any) {
      window.alert(err.message || 'Failed to update preferences')
    }
  }

  const filteredAlerts = alerts.filter((a) => {
    if (alertFilter === 'ALL') return true
    return a.status === alertFilter
  })

  return (
    <div
      style={{
        background: '#ffffff',
        borderRadius: '16px',
        border: '1px solid #e2e8f0',
        boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.05)',
        marginTop: '24px',
        overflow: 'hidden',
      }}
    >
      {/* Top Banner / User header */}
      <div
        style={{
          padding: '24px',
          background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)',
          color: '#ffffff',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '16px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div
            style={{
              width: '52px',
              height: '52px',
              borderRadius: '50%',
              background: '#2563eb',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '1.4rem',
              fontWeight: 700,
              color: '#ffffff',
            }}
          >
            {(profile?.full_name || profile?.email || 'U')[0].toUpperCase()}
          </div>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.35rem', fontWeight: 700 }}>
              {profile?.full_name || 'My PriceTruth Account'}
            </h2>
            <div style={{ color: '#94a3b8', fontSize: '0.85rem', marginTop: '4px' }}>
              {profile?.email} · Supabase Identity Linked
            </div>
          </div>
        </div>

        <button
          onClick={onSignOut}
          style={{
            padding: '8px 18px',
            borderRadius: '8px',
            border: '1px solid #475569',
            background: 'transparent',
            color: '#f8fafc',
            fontSize: '0.85rem',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Sign Out
        </button>
      </div>

      {/* Navigation Tabs */}
      <div
        style={{
          display: 'flex',
          borderBottom: '1px solid #e2e8f0',
          background: '#f8fafc',
          overflowX: 'auto',
        }}
      >
        <button
          onClick={() => setActiveTab('alerts')}
          style={{
            padding: '14px 20px',
            border: 'none',
            background: activeTab === 'alerts' ? '#ffffff' : 'transparent',
            color: activeTab === 'alerts' ? '#2563eb' : '#64748b',
            fontWeight: 600,
            fontSize: '0.9rem',
            borderBottom: activeTab === 'alerts' ? '2px solid #2563eb' : 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          My Alerts
          <span
            style={{
              background: activeTab === 'alerts' ? '#dbeafe' : '#e2e8f0',
              color: activeTab === 'alerts' ? '#1e40af' : '#475569',
              borderRadius: '12px',
              padding: '2px 8px',
              fontSize: '0.75rem',
            }}
          >
            {alerts.length}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('saved')}
          style={{
            padding: '14px 20px',
            border: 'none',
            background: activeTab === 'saved' ? '#ffffff' : 'transparent',
            color: activeTab === 'saved' ? '#2563eb' : '#64748b',
            fontWeight: 600,
            fontSize: '0.9rem',
            borderBottom: activeTab === 'saved' ? '2px solid #2563eb' : 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          Saved Products
          <span
            style={{
              background: activeTab === 'saved' ? '#dbeafe' : '#e2e8f0',
              color: activeTab === 'saved' ? '#1e40af' : '#475569',
              borderRadius: '12px',
              padding: '2px 8px',
              fontSize: '0.75rem',
            }}
          >
            {savedProducts.length}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('history')}
          style={{
            padding: '14px 20px',
            border: 'none',
            background: activeTab === 'history' ? '#ffffff' : 'transparent',
            color: activeTab === 'history' ? '#2563eb' : '#64748b',
            fontWeight: 600,
            fontSize: '0.9rem',
            borderBottom: activeTab === 'history' ? '2px solid #2563eb' : 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          Alert History
          <span
            style={{
              background: activeTab === 'history' ? '#dbeafe' : '#e2e8f0',
              color: activeTab === 'history' ? '#1e40af' : '#475569',
              borderRadius: '12px',
              padding: '2px 8px',
              fontSize: '0.75rem',
            }}
          >
            {history.length}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('notifications')}
          style={{
            padding: '14px 20px',
            border: 'none',
            background: activeTab === 'notifications' ? '#ffffff' : 'transparent',
            color: activeTab === 'notifications' ? '#2563eb' : '#64748b',
            fontWeight: 600,
            fontSize: '0.9rem',
            borderBottom: activeTab === 'notifications' ? '2px solid #2563eb' : 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          Notifications
          {hasUnread && (
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: '#ef4444',
              }}
            />
          )}
        </button>

        <button
          onClick={() => setActiveTab('settings')}
          style={{
            padding: '14px 20px',
            border: 'none',
            background: activeTab === 'settings' ? '#ffffff' : 'transparent',
            color: activeTab === 'settings' ? '#2563eb' : '#64748b',
            fontWeight: 600,
            fontSize: '0.9rem',
            borderBottom: activeTab === 'settings' ? '2px solid #2563eb' : 'none',
            cursor: 'pointer',
          }}
        >
          Settings
        </button>
      </div>

      {/* Feedback banner */}
      {feedback && (
        <div
          style={{
            padding: '12px 24px',
            background: '#eff6ff',
            borderBottom: '1px solid #bfdbfe',
            color: '#1d4ed8',
            fontSize: '0.85rem',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span>{feedback}</span>
          <button
            onClick={() => setFeedback(null)}
            style={{
              background: 'none',
              border: 'none',
              color: '#1d4ed8',
              cursor: 'pointer',
              fontWeight: 700,
            }}
          >
            ×
          </button>
        </div>
      )}

      {/* Content Area */}
      <div style={{ padding: '24px' }}>
        {/* ========================================== */}
        {/* TAB 1: MY ALERTS */}
        {/* ========================================== */}
        {activeTab === 'alerts' && (
          <div>
            {/* Filter Pills */}
            <div
              style={{
                display: 'flex',
                gap: '8px',
                marginBottom: '20px',
                flexWrap: 'wrap',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', gap: '8px' }}>
                {(['ALL', 'ACTIVE', 'TRIGGERED', 'PAUSED'] as const).map((filter) => (
                  <button
                    key={filter}
                    onClick={() => setAlertFilter(filter)}
                    style={{
                      padding: '6px 14px',
                      borderRadius: '20px',
                      border: alertFilter === filter ? '1px solid #2563eb' : '1px solid #cbd5e1',
                      background: alertFilter === filter ? '#eff6ff' : '#ffffff',
                      color: alertFilter === filter ? '#2563eb' : '#475569',
                      fontSize: '0.8rem',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    {filter === 'ALL'
                      ? `All (${alerts.length})`
                      : filter === 'ACTIVE'
                      ? `Active (${alerts.filter((a) => a.status === 'ACTIVE').length})`
                      : filter === 'TRIGGERED'
                      ? `Triggered (${alerts.filter((a) => a.status === 'TRIGGERED').length})`
                      : `Paused (${alerts.filter((a) => a.status === 'PAUSED').length})`}
                  </button>
                ))}
              </div>
            </div>

            {loading ? (
              <div style={{ textAlign: 'center', padding: '40px', color: '#64748b' }}>
                Loading your price alerts...
              </div>
            ) : filteredAlerts.length === 0 ? (
              <div
                style={{
                  textAlign: 'center',
                  padding: '48px 24px',
                  background: '#f8fafc',
                  borderRadius: '12px',
                  border: '1px dashed #cbd5e1',
                }}
              >
                <div style={{ fontSize: '1.1rem', fontWeight: 600, color: '#334155' }}>
                  No alerts found in this view
                </div>
                <p style={{ color: '#64748b', fontSize: '0.85rem', margin: '8px 0 0' }}>
                  Inspect any product and click "Set Alert" to monitor price drops across platforms.
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                {filteredAlerts.map((alert) => {
                  const statusColors: Record<string, { bg: string; text: string; border: string }> = {
                    ACTIVE: { bg: '#f0fdf4', text: '#16a34a', border: '#bbf7d0' },
                    TRIGGERED: { bg: '#fef2f2', text: '#dc2626', border: '#fecaca' },
                    PAUSED: { bg: '#f1f5f9', text: '#64748b', border: '#e2e8f0' },
                    EXPIRED: { bg: '#f8fafc', text: '#94a3b8', border: '#e2e8f0' },
                  }
                  const badge = statusColors[alert.status] || statusColors.ACTIVE

                  return (
                    <div
                      key={alert.id}
                      style={{
                        padding: '18px 20px',
                        borderRadius: '12px',
                        border: '1px solid #e2e8f0',
                        background: '#ffffff',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '12px',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'flex-start',
                          flexWrap: 'wrap',
                          gap: '10px',
                        }}
                      >
                        <div style={{ flex: 1, minWidth: '240px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span
                              style={{
                                fontSize: '0.7rem',
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                padding: '2px 8px',
                                borderRadius: '4px',
                                background: badge.bg,
                                color: badge.text,
                                border: `1px solid ${badge.border}`,
                              }}
                            >
                              {alert.status}
                            </span>
                            {alert.listing && (
                              <span
                                style={{
                                  fontSize: '0.75rem',
                                  color: '#64748b',
                                  background: '#f1f5f9',
                                  padding: '2px 8px',
                                  borderRadius: '4px',
                                }}
                              >
                                {alert.listing.platform}
                              </span>
                            )}
                            <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                              Created {new Date(alert.created_at).toLocaleDateString()}
                            </span>
                          </div>

                          <h4
                            style={{
                              margin: '6px 0 2px',
                              fontSize: '1rem',
                              fontWeight: 700,
                              color: '#0f172a',
                            }}
                          >
                            {alert.product?.title || alert.name || `Alert #${alert.id}`}
                          </h4>

                          <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
                            Mode:{' '}
                            <strong style={{ color: '#334155' }}>
                              {alert.mode.replace(/_/g, ' ')}
                            </strong>
                          </div>
                        </div>

                        {/* Price Target vs Current */}
                        <div
                          style={{
                            display: 'flex',
                            gap: '20px',
                            background: '#f8fafc',
                            padding: '10px 16px',
                            borderRadius: '8px',
                            alignItems: 'center',
                          }}
                        >
                          <div>
                            <div style={{ fontSize: '0.7rem', color: '#64748b', textTransform: 'uppercase' }}>
                              Target Price
                            </div>
                            <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#2563eb' }}>
                              {formatINR(alert.target_price)}
                            </div>
                          </div>

                          <div style={{ height: '24px', width: '1px', background: '#cbd5e1' }} />

                          <div>
                            <div style={{ fontSize: '0.7rem', color: '#64748b', textTransform: 'uppercase' }}>
                              {alert.status === 'TRIGGERED' ? 'Triggered Price' : 'Current Price'}
                            </div>
                            <div
                              style={{
                                fontSize: '1.05rem',
                                fontWeight: 700,
                                color: alert.status === 'TRIGGERED' ? '#dc2626' : '#0f172a',
                              }}
                            >
                              {alert.status === 'TRIGGERED'
                                ? formatINR(alert.trigger_price)
                                : formatINR(alert.current_lowest_price)}
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Triggered notice & action buttons */}
                      {alert.status === 'TRIGGERED' && (
                        <div
                          style={{
                            padding: '8px 12px',
                            background: '#fef2f2',
                            borderRadius: '6px',
                            border: '1px solid #fee2e2',
                            fontSize: '0.8rem',
                            color: '#b91c1c',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            flexWrap: 'wrap',
                            gap: '8px',
                          }}
                        >
                          <span>
                            Triggered on{' '}
                            {alert.triggered_at ? new Date(alert.triggered_at).toLocaleString() : 'recently'}{' '}
                            at <strong>{formatINR(alert.trigger_price)}</strong>.
                          </span>
                          <button
                            onClick={() => {
                              setLowerAlertProduct({
                                id: alert.product_id,
                                title: alert.product?.title || `Product #${alert.product_id}`,
                                currentPrice: alert.trigger_price || alert.current_lowest_price,
                              })
                              setLowerTargetInput(
                                alert.trigger_price
                                  ? String(Math.round(alert.trigger_price * 0.95))
                                  : ''
                              )
                            }}
                            style={{
                              padding: '4px 10px',
                              borderRadius: '4px',
                              border: '1px solid #b91c1c',
                              background: '#ffffff',
                              color: '#b91c1c',
                              fontSize: '0.75rem',
                              fontWeight: 700,
                              cursor: 'pointer',
                            }}
                          >
                            + Set Lower Target Alert
                          </button>
                        </div>
                      )}

                      {/* Bottom action controls */}
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          borderTop: '1px solid #f1f5f9',
                          paddingTop: '10px',
                          flexWrap: 'wrap',
                          gap: '8px',
                        }}
                      >
                        <div style={{ display: 'flex', gap: '8px' }}>
                          <button
                            onClick={() => {
                              setChartProductId(alert.product_id)
                              setChartProductTitle(alert.product?.title || `Product #${alert.product_id}`)
                            }}
                            style={{
                              padding: '5px 12px',
                              borderRadius: '6px',
                              border: '1px solid #cbd5e1',
                              background: '#ffffff',
                              color: '#334155',
                              fontSize: '0.75rem',
                              fontWeight: 600,
                              cursor: 'pointer',
                            }}
                          >
                            View Price History Chart
                          </button>

                          {alert.product?.origin_url && onInspectProduct && (
                            <button
                              onClick={() => onInspectProduct(alert.product!.origin_url!)}
                              style={{
                                padding: '5px 12px',
                                borderRadius: '6px',
                                border: '1px solid #cbd5e1',
                                background: '#ffffff',
                                color: '#334155',
                                fontSize: '0.75rem',
                                fontWeight: 600,
                                cursor: 'pointer',
                              }}
                            >
                              Inspect Live
                            </button>
                          )}
                        </div>

                        <div style={{ display: 'flex', gap: '8px' }}>
                          <button
                            onClick={() => {
                              setEditingAlert(alert)
                              setNewTargetPrice(alert.target_price ? String(alert.target_price) : '')
                            }}
                            style={{
                              padding: '5px 12px',
                              borderRadius: '6px',
                              border: '1px solid #cbd5e1',
                              background: '#ffffff',
                              color: '#334155',
                              fontSize: '0.75rem',
                              fontWeight: 600,
                              cursor: 'pointer',
                            }}
                          >
                            Edit Target
                          </button>

                          <button
                            onClick={() => handleTogglePause(alert)}
                            style={{
                              padding: '5px 12px',
                              borderRadius: '6px',
                              border: '1px solid #cbd5e1',
                              background: '#ffffff',
                              color: '#334155',
                              fontSize: '0.75rem',
                              fontWeight: 600,
                              cursor: 'pointer',
                            }}
                          >
                            {alert.status === 'PAUSED' ? 'Resume' : 'Pause'}
                          </button>

                          {deleteConfirmAlertId === alert.id ? (
                            <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                              <span style={{ fontSize: '0.75rem', color: '#dc2626' }}>Delete?</span>
                              <button
                                onClick={() => handleDeleteAlert(alert.id)}
                                style={{
                                  padding: '4px 8px',
                                  borderRadius: '4px',
                                  border: 'none',
                                  background: '#dc2626',
                                  color: '#ffffff',
                                  fontSize: '0.75rem',
                                  fontWeight: 600,
                                  cursor: 'pointer',
                                }}
                              >
                                Yes
                              </button>
                              <button
                                onClick={() => setDeleteConfirmAlertId(null)}
                                style={{
                                  padding: '4px 8px',
                                  borderRadius: '4px',
                                  border: '1px solid #cbd5e1',
                                  background: '#ffffff',
                                  color: '#334155',
                                  fontSize: '0.75rem',
                                  cursor: 'pointer',
                                }}
                              >
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button
                              onClick={() => setDeleteConfirmAlertId(alert.id)}
                              style={{
                                padding: '5px 12px',
                                borderRadius: '6px',
                                border: '1px solid #fecaca',
                                background: '#ffffff',
                                color: '#dc2626',
                                fontSize: '0.75rem',
                                fontWeight: 600,
                                cursor: 'pointer',
                              }}
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* ========================================== */}
        {/* TAB 2: SAVED PRODUCTS */}
        {/* ========================================== */}
        {activeTab === 'saved' && (
          <div>
            {savedProducts.length === 0 ? (
              <div
                style={{
                  textAlign: 'center',
                  padding: '48px 24px',
                  background: '#f8fafc',
                  borderRadius: '12px',
                  border: '1px dashed #cbd5e1',
                }}
              >
                <div style={{ fontSize: '1.1rem', fontWeight: 600, color: '#334155' }}>
                  No saved products yet
                </div>
                <p style={{ color: '#64748b', fontSize: '0.85rem', margin: '8px 0 0' }}>
                  When inspecting any product, click "Save Product" to store it here for easy tracking.
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {savedProducts.map((p) => (
                  <div
                    key={p.id}
                    style={{
                      padding: '16px 20px',
                      borderRadius: '12px',
                      border: '1px solid #e2e8f0',
                      background: '#ffffff',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      flexWrap: 'wrap',
                      gap: '12px',
                    }}
                  >
                    <div style={{ flex: 1, minWidth: '240px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        {p.origin_platform && (
                          <span
                            style={{
                              fontSize: '0.75rem',
                              fontWeight: 600,
                              color: '#64748b',
                              background: '#f1f5f9',
                              padding: '2px 8px',
                              borderRadius: '4px',
                            }}
                          >
                            {p.origin_platform}
                          </span>
                        )}
                        <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                          Saved {new Date(p.saved_at).toLocaleDateString()}
                        </span>
                      </div>

                      <h4
                        style={{
                          margin: '6px 0 2px',
                          fontSize: '1rem',
                          fontWeight: 700,
                          color: '#0f172a',
                        }}
                      >
                        {p.title}
                      </h4>

                      <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
                        Lowest Verified:{' '}
                        <strong style={{ color: '#16a34a', fontSize: '0.9rem' }}>
                          {formatINR(p.current_lowest_price)}
                        </strong>
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                      <button
                        onClick={() => {
                          setChartProductId(p.product_id)
                          setChartProductTitle(p.title)
                        }}
                        style={{
                          padding: '6px 12px',
                          borderRadius: '6px',
                          border: '1px solid #cbd5e1',
                          background: '#ffffff',
                          color: '#334155',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        Price Chart
                      </button>

                      <button
                        onClick={() => {
                          setLowerAlertProduct({
                            id: p.product_id,
                            title: p.title,
                            currentPrice: p.current_lowest_price,
                          })
                          setLowerTargetInput(
                            p.current_lowest_price
                              ? String(Math.round(p.current_lowest_price * 0.95))
                              : ''
                          )
                        }}
                        style={{
                          padding: '6px 12px',
                          borderRadius: '6px',
                          border: 'none',
                          background: '#2563eb',
                          color: '#ffffff',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        + Set Alert
                      </button>

                      {p.origin_url && onInspectProduct && (
                        <button
                          onClick={() => onInspectProduct(p.origin_url!)}
                          style={{
                            padding: '6px 12px',
                            borderRadius: '6px',
                            border: '1px solid #cbd5e1',
                            background: '#ffffff',
                            color: '#334155',
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            cursor: 'pointer',
                          }}
                        >
                          Inspect
                        </button>
                      )}

                      {deleteConfirmProductId === p.product_id ? (
                        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                          <button
                            onClick={() => handleRemoveSaved(p.product_id)}
                            style={{
                              padding: '5px 8px',
                              borderRadius: '4px',
                              border: 'none',
                              background: '#dc2626',
                              color: '#ffffff',
                              fontSize: '0.75rem',
                              fontWeight: 600,
                              cursor: 'pointer',
                            }}
                          >
                            Remove
                          </button>
                          <button
                            onClick={() => setDeleteConfirmProductId(null)}
                            style={{
                              padding: '5px 8px',
                              borderRadius: '4px',
                              border: '1px solid #cbd5e1',
                              background: '#ffffff',
                              color: '#334155',
                              fontSize: '0.75rem',
                              cursor: 'pointer',
                            }}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setDeleteConfirmProductId(p.product_id)}
                          style={{
                            padding: '6px 10px',
                            borderRadius: '6px',
                            border: '1px solid #fecaca',
                            background: '#ffffff',
                            color: '#dc2626',
                            fontSize: '0.75rem',
                            cursor: 'pointer',
                          }}
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ========================================== */}
        {/* TAB 3: ALERT HISTORY */}
        {/* ========================================== */}
        {activeTab === 'history' && (
          <div>
            {history.length === 0 ? (
              <div
                style={{
                  textAlign: 'center',
                  padding: '48px 24px',
                  background: '#f8fafc',
                  borderRadius: '12px',
                  border: '1px dashed #cbd5e1',
                }}
              >
                <div style={{ fontSize: '1.1rem', fontWeight: 600, color: '#334155' }}>
                  No trigger events yet
                </div>
                <p style={{ color: '#64748b', fontSize: '0.85rem', margin: '8px 0 0' }}>
                  When an active alert reaches your target price or detects a verified price drop, its trigger history will be logged here.
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {history.map((ev) => (
                  <div
                    key={ev.id}
                    style={{
                      padding: '16px 20px',
                      borderRadius: '10px',
                      border: '1px solid #e2e8f0',
                      background: '#ffffff',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      flexWrap: 'wrap',
                      gap: '12px',
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span
                          style={{
                            fontSize: '0.7rem',
                            fontWeight: 700,
                            padding: '2px 8px',
                            borderRadius: '4px',
                            background: '#fef2f2',
                            color: '#dc2626',
                            textTransform: 'uppercase',
                          }}
                        >
                          {ev.kind.replace(/_/g, ' ')}
                        </span>
                        {ev.platform && (
                          <span
                            style={{
                              fontSize: '0.75rem',
                              color: '#64748b',
                              background: '#f1f5f9',
                              padding: '2px 8px',
                              borderRadius: '4px',
                            }}
                          >
                            {ev.platform}
                          </span>
                        )}
                      </div>

                      <div style={{ fontWeight: 600, color: '#0f172a', margin: '6px 0 2px' }}>
                        {ev.product_title || `Product #${ev.product_id}`}
                      </div>
                      <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
                        {ev.message}
                      </div>
                    </div>

                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#16a34a' }}>
                        {formatINR(ev.trigger_price)}
                      </div>
                      {ev.previous_price && (
                        <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                          Previous: {formatINR(ev.previous_price)}
                          {ev.price_delta ? ` (${formatINR(ev.price_delta)})` : ''}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ========================================== */}
        {/* TAB 4: NOTIFICATIONS */}
        {/* ========================================== */}
        {activeTab === 'notifications' && (
          <div>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '16px',
              }}
            >
              <h4 style={{ margin: 0, fontSize: '1rem', color: '#0f172a' }}>
                In-App Notifications
              </h4>
              {notifications.some((n) => !n.is_read) && (
                <button
                  onClick={handleMarkAllNotifs}
                  style={{
                    padding: '4px 12px',
                    borderRadius: '6px',
                    border: '1px solid #cbd5e1',
                    background: '#ffffff',
                    color: '#2563eb',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Mark All Read
                </button>
              )}
            </div>

            {notifications.length === 0 ? (
              <div
                style={{
                  textAlign: 'center',
                  padding: '48px 24px',
                  background: '#f8fafc',
                  borderRadius: '12px',
                  border: '1px dashed #cbd5e1',
                }}
              >
                <div style={{ fontSize: '1rem', fontWeight: 600, color: '#334155' }}>
                  No notifications yet
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {notifications.map((n) => (
                  <div
                    key={n.id}
                    onClick={() => !n.is_read && handleMarkNotif(n.id)}
                    style={{
                      padding: '14px 18px',
                      borderRadius: '8px',
                      border: '1px solid #e2e8f0',
                      background: n.is_read ? '#ffffff' : '#f0f9ff',
                      cursor: n.is_read ? 'default' : 'pointer',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        {!n.is_read && (
                          <span
                            style={{
                              width: '6px',
                              height: '6px',
                              borderRadius: '50%',
                              background: '#2563eb',
                            }}
                          />
                        )}
                        <strong style={{ fontSize: '0.9rem', color: '#0f172a' }}>
                          {n.title}
                        </strong>
                      </div>
                      <p style={{ margin: '4px 0 0', fontSize: '0.8rem', color: '#475569' }}>
                        {n.message}
                      </p>
                    </div>

                    <span style={{ fontSize: '0.7rem', color: '#94a3b8' }}>
                      {new Date(n.created_at).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ========================================== */}
        {/* TAB 5: SETTINGS */}
        {/* ========================================== */}
        {activeTab === 'settings' && (
          <form onSubmit={handleSaveSettings} style={{ maxWidth: '480px' }}>
            <h4 style={{ margin: '0 0 16px', fontSize: '1.05rem', color: '#0f172a' }}>
              Account & Refresh Preferences
            </h4>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                Display Name
              </label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  border: '1px solid #cbd5e1',
                  fontSize: '0.95rem',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                Default Alert Check Frequency
              </label>
              <select
                value={checkInterval}
                onChange={(e) => setCheckInterval(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  border: '1px solid #cbd5e1',
                  fontSize: '0.95rem',
                  boxSizing: 'border-box',
                  background: '#ffffff',
                }}
              >
                <option value="60">Every 1 Hour (Fast price shifts)</option>
                <option value="360">Every 6 Hours (Standard)</option>
                <option value="720">Every 12 Hours</option>
                <option value="1440">Once a Day (24 Hours)</option>
              </select>
            </div>

            <button
              type="submit"
              style={{
                padding: '10px 20px',
                borderRadius: '8px',
                border: 'none',
                background: '#2563eb',
                color: '#ffffff',
                fontWeight: 600,
                fontSize: '0.9rem',
                cursor: 'pointer',
              }}
            >
              Save Preferences
            </button>
          </form>
        )}
      </div>

      {/* ========================================== */}
      {/* EDIT TARGET PRICE MODAL */}
      {/* ========================================== */}
      {editingAlert && (
        <div
          className="modal-backdrop"
          onClick={() => setEditingAlert(null)}
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
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#ffffff',
              borderRadius: '16px',
              width: '100%',
              maxWidth: '400px',
              padding: '24px',
              boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
            }}
          >
            <h3 style={{ margin: '0 0 12px', fontSize: '1.15rem', color: '#0f172a' }}>
              Edit Target Price
            </h3>
            <p style={{ margin: '0 0 16px', fontSize: '0.85rem', color: '#64748b' }}>
              Updating target price will reactivate this alert.
            </p>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                New Target Price (₹ INR)
              </label>
              <input
                type="number"
                value={newTargetPrice}
                onChange={(e) => setNewTargetPrice(e.target.value)}
                placeholder="e.g. 45000"
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  border: '1px solid #cbd5e1',
                  fontSize: '1rem',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setEditingAlert(null)}
                style={{
                  padding: '8px 16px',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                  background: '#ffffff',
                  color: '#334155',
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleUpdateTarget}
                style={{
                  padding: '8px 16px',
                  borderRadius: '6px',
                  border: 'none',
                  background: '#2563eb',
                  color: '#ffffff',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Save & Activate
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================== */}
      {/* SECONDARY / LOWER TARGET ALERT MODAL */}
      {/* ========================================== */}
      {lowerAlertProduct && (
        <div
          className="modal-backdrop"
          onClick={() => setLowerAlertProduct(null)}
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
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#ffffff',
              borderRadius: '16px',
              width: '100%',
              maxWidth: '440px',
              padding: '24px',
              boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
            }}
          >
            <h3 style={{ margin: '0 0 8px', fontSize: '1.2rem', color: '#0f172a' }}>
              Set Next Target Price Alert
            </h3>
            <p style={{ margin: '0 0 16px', fontSize: '0.85rem', color: '#64748b' }}>
              Create an independent alert for <strong>{lowerAlertProduct.title.slice(0, 45)}...</strong> that will trigger when the price drops further.
            </p>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                Next Target Price (₹ INR)
              </label>
              <input
                type="number"
                value={lowerTargetInput}
                onChange={(e) => setLowerTargetInput(e.target.value)}
                placeholder="e.g. 42000"
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  border: '1px solid #cbd5e1',
                  fontSize: '1rem',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setLowerAlertProduct(null)}
                style={{
                  padding: '8px 16px',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                  background: '#ffffff',
                  color: '#334155',
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleCreateLowerAlert}
                style={{
                  padding: '8px 16px',
                  borderRadius: '6px',
                  border: 'none',
                  background: '#2563eb',
                  color: '#ffffff',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Create Independent Alert
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================== */}
      {/* PRICE HISTORY CHART MODAL */}
      {/* ========================================== */}
      {chartProductId && (
        <PriceHistoryChart
          productId={chartProductId}
          productTitle={chartProductTitle}
          isOpen={true}
          onClose={() => setChartProductId(null)}
        />
      )}
    </div>
  )
}
