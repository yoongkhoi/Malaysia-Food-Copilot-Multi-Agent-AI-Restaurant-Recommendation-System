import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, discover, savePreference } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api client', () => {
  it('posts the discovery query and returns the payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      answer: 'none',
      results: [],
      exclusion_counts: { price_unverified: 1 },
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const result = await discover('Old Klang Road under RM20')
    expect(result.results).toEqual([])
    expect(result.exclusion_counts.price_unverified).toBe(1)
    const [, init] = fetchMock.mock.calls[0]
    expect(JSON.parse(init.body)).toEqual({ query: 'Old Klang Road under RM20' })
  })

  it('does not treat a failed preference save as success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: 'Memory stores are not configured',
    }), { status: 503 })))
    await expect(savePreference('user', 'ambience', 'quiet', true)).rejects.toBeInstanceOf(ApiError)
  })

  it('reports a network failure instead of an empty success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    await expect(discover('Old Klang Road')).rejects.toMatchObject({ status: 0 })
  })
})
