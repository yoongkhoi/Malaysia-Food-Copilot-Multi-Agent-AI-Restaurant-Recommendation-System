import { describe, expect, it } from 'vitest'
import { evidenceLines } from './evidence'

describe('evidenceLines', () => {
  it('keeps canonical source separate from identity and location', () => {
    const lines = evidenceLines({
      dataset_origin: 'canonical',
      name: 'Example Sushi',
      location_verified: false,
      stored_address: null,
    })
    expect(lines[0]).toContain('canonical OSM record')
    expect(lines[1]).toContain('not verified')
    expect(lines[2]).toContain('not on file')
    expect(lines[3]).toBe('Operating status: not recorded')
  })

  it('does not call a stored address verified', () => {
    const lines = evidenceLines({
      name: 'KFC',
      location_verified: false,
      stored_address: 'Jalan Example',
    })
    expect(lines[2]).toContain('stored but not verified')
  })
})
