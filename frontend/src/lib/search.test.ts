import { describe, expect, it } from 'vitest'
import { buildDiscoveryQuery, followUpContext } from './search'

describe('buildDiscoveryQuery', () => {
  it('adds Old Klang Road when the text does not name an area', () => {
    expect(buildDiscoveryQuery({ text: 'Korean BBQ' })).toBe('Korean BBQ Old Klang Road')
  })

  it('keeps an area the user already typed', () => {
    expect(buildDiscoveryQuery({ text: 'Japanese restaurant in Kuala Lumpur' })).toBe('Japanese restaurant in Kuala Lumpur')
  })
})

describe('followUpContext', () => {
  it('keeps every restaurant already shown in this session, not only the last page', () => {
    const context = followUpContext([
      {
        role: 'assistant',
        response: {
          constraints: { region: 'old_klang_road', cuisine: 'korean', cuisines: ['korean'] },
          results: [{ name: 'First', restaurant_id: 'first' }],
        },
      },
      {
        role: 'assistant',
        response: {
          constraints: { region: 'old_klang_road', cuisine: 'korean', cuisines: ['korean'] },
          results: [{ name: 'Second', restaurant_id: 'second' }],
        },
      },
    ])
    expect(context?.shown_ids).toEqual(['first', 'second'])
    expect(context?.region).toBe('old_klang_road')
    expect(context?.cuisine).toBe('korean')
  })

  it('does not carry a general answer or an empty session into the next request', () => {
    expect(followUpContext([
      { role: 'assistant', response: { intent: 'general_qa', constraints: { region: 'kuala_lumpur' }, results: [] } },
    ])).toBeUndefined()
    expect(followUpContext([])).toBeUndefined()
  })
})
