import { describe, expect, it } from 'vitest'
import { memoryStatusText } from './memoryStatus'

describe('memory status copy', () => {
  it('shows the server note instead of a blanket saved message', () => {
    expect(memoryStatusText({
      memory_saved: false,
      memory_note: 'The reply is in the session cache. The database copy failed.',
    })).toBe('The reply is in the session cache. The database copy failed.')
  })

  it('uses the confirmed note only when both stores succeeded', () => {
    expect(memoryStatusText({
      memory_saved: true,
      memory_note: 'This turn was saved in the session cache and the database.',
    })).toContain('session cache and the database')
  })

  it('does not invent success when the note is empty and nothing was saved', () => {
    expect(memoryStatusText({ memory_saved: false, memory_note: '' })).toBe('This turn was not saved.')
  })
})
