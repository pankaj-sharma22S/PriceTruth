import type { Comparison, DiscoveryRun, Platform, TrackingJob } from '../types'

// Use the frontend origin by default so this also works when the UI is opened
// through a LAN address or a remote browser. Vite proxies /api to the backend.
const apiBase = import.meta.env.VITE_API_BASE_URL ?? '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
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

export const inspectProduct = (url: string) => request<Comparison>('/products/inspect', { method: 'POST', body: JSON.stringify({ url }) })
export const getProduct = (id: number) => request<Comparison>(`/products/${id}`)
export const getPlatforms = () => request<{ platforms: Platform[] }>('/platforms')
export const getDiscovery = (id: number) => request<DiscoveryRun>(`/discovery/${id}`)
export const addDiscoveryCandidate = (run_id: number, url: string) => request<{run_id:number;platform:string;status:string}>(`/discovery/${run_id}/candidates`, { method: 'POST', body: JSON.stringify({ url }) })
export const getHistory = (id: number) => request<{ observations: { price: string; currency: string; observed_at: string; platform: string }[] }>(`/products/${id}/history`)
export const createTracking = (product_id: number, mode: 'any_drop' | 'target_price', target_price?: number, listing_id?: number) => request<TrackingJob>('/tracking', { method: 'POST', body: JSON.stringify({ product_id, mode, target_price: target_price ?? null, listing_id: listing_id ?? null }) })
export const getTracking = () => request<{ tracking: TrackingJob[] }>('/tracking')
export const setTracking = (id: number, active: boolean) => request<{ id: number; active: boolean }>(`/tracking/${id}`, { method: 'PATCH', body: JSON.stringify({ active }) })
export const getAlerts = () => request<{ alerts: { id: number; tracking_id: number; listing_id: number; kind: string; message: string; created_at: string }[] }>('/alerts')
