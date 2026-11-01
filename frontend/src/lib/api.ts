import type {
  AlertEvent,
  Comparison,
  DataCalculations,
  DiscoveryRun,
  Platform,
  PriceAlert,
  PriceHistoryResponse,
  SavedProduct,
  TrackingJob,
  UserAlertHistoryEvent,
  UserNotification,
  UserProfile,
} from '../types'
import { getAccessToken } from './supabaseClient'
import { getVercelApiUrl } from '../config/api.vercel'

// Resolves the active API base URL:
// 1. If Vercel deployment provides VITE_API_URL, use that remote backend endpoint.
// 2. Otherwise fall back to VITE_API_BASE_URL or local default '/api'.
// In local development, '/api' is proxied by Vite directly to http://localhost:8000.
const apiBase = getVercelApiUrl() ?? import.meta.env.VITE_API_BASE_URL ?? '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAccessToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> || {}),
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, {
      ...init,
      headers,
    })
  } catch {
    throw new Error(`Could not reach the PriceTruth API at ${apiBase}. Make sure the backend is running.`)
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.source?.message ?? `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const getJob = (jobId: string) =>
  request<{ job_id: string; status: string; result: Comparison | null; error: string | null }>(`/jobs/${jobId}`)

export const inspectProduct = async (url: string): Promise<Comparison> => {
  const initial = await request<any>('/products/inspect', { method: 'POST', body: JSON.stringify({ url }) })

  // If result is already completed or contains product (e.g. from cache or inline)
  if (initial.product && initial.offers?.length) {
    return initial as Comparison
  }

  // If a background job was queued (PENDING / RUNNING)
  if (initial.job_id && (initial.status === 'PENDING' || initial.status === 'RUNNING')) {
    const startTime = Date.now()
    while (Date.now() - startTime < 45000) {
      await new Promise(r => setTimeout(r, 800))
      const job = await getJob(initial.job_id)
      if (job.status === 'COMPLETED' && job.result) {
        return job.result
      }
      if (job.status === 'PARTIAL' && job.result?.product) {
        return job.result
      }
      if (job.status === 'FAILED') {
        throw new Error(job.error || 'Product inspection failed.')
      }
    }
    throw new Error('Product inspection timed out in background queue.')
  }

  return initial as Comparison
}

export const getProduct = (id: number) => request<Comparison>(`/products/${id}`)
export const getPlatforms = () => request<{ platforms: Platform[] }>('/platforms')
export const getDiscovery = (id: number) => request<DiscoveryRun>(`/discovery/${id}`)
export const addDiscoveryCandidate = (run_id: number, url: string) =>
  request<{ run_id: number; platform: string; status: string }>(`/discovery/${run_id}/candidates`, {
    method: 'POST',
    body: JSON.stringify({ url }),
  })
export const getHistory = (id: number) =>
  request<{ observations: { price: string; currency: string; observed_at: string; platform: string }[] }>(
    `/products/${id}/history`
  )

export const createTracking = (
  product_id: number,
  mode: TrackingJob['mode'],
  target_price?: number,
  threshold_percent?: number,
  interval_minutes: number = 360,
  name?: string,
  listing_id?: number
) =>
  request<TrackingJob>('/tracking', {
    method: 'POST',
    body: JSON.stringify({
      product_id,
      mode,
      target_price: target_price ?? null,
      threshold_percent: threshold_percent ?? null,
      interval_minutes,
      name: name ?? null,
      listing_id: listing_id ?? null,
    }),
  })

export const getTracking = () => request<{ tracking: TrackingJob[] }>('/tracking')

export const updateTracking = (
  id: number,
  updates: { active?: boolean; target_price?: number; threshold_percent?: number; interval_minutes?: number; name?: string }
) => request<TrackingJob>(`/tracking/${id}`, { method: 'PATCH', body: JSON.stringify(updates) })

export const setTracking = (id: number, active: boolean) => updateTracking(id, { active })

export const deleteTracking = (id: number) => request<{ deleted: boolean; id: number }>(`/tracking/${id}`, { method: 'DELETE' })

export const getTrackingHistory = (id: number) => request<{ events: AlertEvent[] }>(`/tracking/${id}/history`)

export const getAlerts = () => request<{ alerts: AlertEvent[] }>('/alerts')

export const getDataCalculations = () => request<DataCalculations>('/data-calculations')

// ==========================================
// Authenticated User & Price Alert APIs
// ==========================================

export const getUserProfile = () => request<UserProfile>('/user/profile')

export const updateUserProfile = (payload: { full_name?: string; preferences?: Record<string, any> }) =>
  request<UserProfile>('/user/profile', { method: 'PATCH', body: JSON.stringify(payload) })

export const getSavedProducts = () => request<{ saved_products: SavedProduct[] }>('/user/products')

export const saveProduct = (product_id: number, notes?: string) =>
  request<{ id: number; product_id: number; saved: boolean }>('/user/products', {
    method: 'POST',
    body: JSON.stringify({ product_id, notes }),
  })

export const removeSavedProduct = (product_id: number) =>
  request<{ status: string; product_id: number }>(`/user/products/${product_id}`, { method: 'DELETE' })

export const getUserAlerts = (status?: string) => {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  return request<{ alerts: PriceAlert[] }>(`/user/alerts${q}`)
}

export const createUserAlert = (payload: {
  product_id: number
  listing_id?: number | null
  name?: string | null
  mode?: PriceAlert['mode']
  target_price?: number | null
  threshold_percent?: number | null
  interval_minutes?: number
}) =>
  request<PriceAlert>('/user/alerts', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const getUserAlert = (alert_id: number) => request<PriceAlert>(`/user/alerts/${alert_id}`)

export const updateUserAlert = (
  alert_id: number,
  payload: {
    name?: string
    mode?: PriceAlert['mode']
    target_price?: number | null
    threshold_percent?: number | null
    status?: PriceAlert['status']
    interval_minutes?: number
  }
) =>
  request<PriceAlert>(`/user/alerts/${alert_id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const deleteUserAlert = (alert_id: number) =>
  request<{ status: string; alert_id: number }>(`/user/alerts/${alert_id}`, { method: 'DELETE' })

export const getUserAlertHistory = () => request<{ history: UserAlertHistoryEvent[] }>('/user/alerts/history')

export const getUserNotifications = (limit: number = 50) =>
  request<{ notifications: UserNotification[]; has_unread: boolean }>(`/user/notifications?limit=${limit}`)

export const markNotificationRead = (notification_id: number) =>
  request<{ status: string; id: number }>(`/user/notifications/${notification_id}/read`, { method: 'PATCH' })

export const markAllNotificationsRead = () =>
  request<{ status: string }>('/user/notifications/read-all', { method: 'POST' })

export const getProductPriceHistory = (product_id: number, range: string = '30d') =>
  request<PriceHistoryResponse>(`/products/${product_id}/price-history?range=${encodeURIComponent(range)}`)
