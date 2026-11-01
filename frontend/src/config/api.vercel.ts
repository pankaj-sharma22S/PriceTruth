/**
 * Vercel-specific API configuration.
 *
 * Reads the deployed backend URL from `import.meta.env.VITE_API_URL`.
 * Normalizes the URL by removing trailing slashes and ensuring the `/api`
 * prefix is appended if not already present.
 *
 * When VITE_API_URL is undefined or empty (such as in local development),
 * this returns `undefined`, allowing the frontend to fall back to the
 * default local configuration (http://localhost:8000 via Vite proxy).
 */
export function getVercelApiUrl(): string | undefined {
  const envUrl = import.meta.env.VITE_API_URL
  if (!envUrl || typeof envUrl !== 'string' || !envUrl.trim()) {
    return undefined
  }

  const normalized = envUrl.trim().replace(/\/+$/, '')
  return normalized.endsWith('/api') ? normalized : `${normalized}/api`
}

export function isVercelConfigured(): boolean {
  return Boolean(import.meta.env.VITE_API_URL && import.meta.env.VITE_API_URL.trim() !== '')
}
