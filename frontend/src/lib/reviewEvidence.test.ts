import { describe, expect, it } from 'vitest'
import { reviewEvidenceLine } from './reviewEvidence'

describe('review evidence copy', () => {
  it('labels a quote as an opinion and keeps the stored rating', () => {
    const line = reviewEvidenceLine({
      restaurant_name: 'Iketeru',
      kind: 'mixed_or_lower_opinion',
      rating: 3,
      source: 'google',
      span: 'Good fish but the room was noisy.',
    })
    expect(line).toContain('Iketeru')
    expect(line).toContain('not a verified fact')
    expect(line).toContain('noisy')
    expect(line).toContain('3')
  })

  it('does not invent a rating when the review has none', () => {
    const line = reviewEvidenceLine({ restaurant_name: 'Example', span: 'A short note.' })
    expect(line).not.toContain('Stored rating')
    expect(line).toContain('A short note.')
  })
})
