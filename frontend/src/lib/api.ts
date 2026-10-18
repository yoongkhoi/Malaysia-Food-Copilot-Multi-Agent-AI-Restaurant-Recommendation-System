import type {
  ChatResponse,
  DiscoveryResponse,
  HealthStatus,
  MemoryStatus,
  Preference,
  RestaurantDetails,
  RestaurantEvidence,
} from '@/types/api'

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function errorMessage(data: unknown, fallback: string): string {
  if (!data || typeof data !== 'object') return fallback
  const detail = (data as { detail?: unknown }).detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object') {
    const nested = detail as { detail?: unknown, error?: unknown }
    if (typeof nested.detail === 'string') return nested.detail
    if (typeof nested.error === 'string') return nested.error
  }
  return fallback
}

export async function request<T>(path: string, init?: RequestInit, timeoutMs = 20000): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${base}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    })
    const text = await response.text()
    const data = text ? JSON.parse(text) as unknown : null
    if (!response.ok) {
      throw new ApiError(response.status, errorMessage(data, response.statusText || 'Request failed'))
    }
    return data as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(0, 'The request timed out.')
    }
    throw new ApiError(0, 'The API could not be reached.')
  } finally {
    clearTimeout(timer)
  }
}

export function discover(query: string) {
  return request<DiscoveryResponse>('/api/discover', {
    method: 'POST',
    body: JSON.stringify({ query }),
  })
}

export function chat(query: string, userId: string, sessionId: string, context?: Record<string, unknown>) {
  return request<ChatResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ query, user_id: userId, session_id: sessionId, context: context ?? null }),
  }, 60000)
}

export function restaurantDetails(restaurantId: string) {
  return request<RestaurantDetails>(`/api/restaurants/${encodeURIComponent(restaurantId)}`)
}

export function restaurantEvidence(restaurantId: string) {
  return request<RestaurantEvidence>(`/api/restaurants/${encodeURIComponent(restaurantId)}/evidence`)
}

export function health() {
  return request<HealthStatus>('/health')
}

export function memoryStatus() {
  return request<MemoryStatus>('/api/memory/status')
}

export function sessionMessages(userId: string, sessionId: string) {
  return request<{ session_id: string, messages: { role: string, content: string }[] }>(
    `/api/memory/sessions/${encodeURIComponent(sessionId)}?user_id=${encodeURIComponent(userId)}`,
  )
}

export function sessionList(userId: string) {
  return request<{ user_id: string, sessions: { session_id: string, started_at: string, preview: string }[] }>(
    `/api/memory/users/${encodeURIComponent(userId)}/sessions`,
  )
}

export function opsBoard() {
  return request<Record<string, unknown>>('/api/ops/board')
}

export function preferences(userId: string) {
  return request<{ user_id: string, preferences: Preference[] }>(
    `/api/memory/preferences/${encodeURIComponent(userId)}`,
  )
}

export function savePreference(userId: string, key: string, value: string, confirmed: boolean) {
  return request<{ user_id: string, key: string, confirmed: boolean }>('/api/memory/preferences', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, key, value, confirmed }),
  })
}

export function deleteUser(userId: string) {
  return request<{ user_id: string, deleted_sessions: string[] }>(
    `/api/memory/users/${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  )
}
