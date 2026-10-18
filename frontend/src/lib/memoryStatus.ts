export function memoryStatusText(response: { memory_saved?: boolean; memory_note?: string }): string {
  if (response.memory_note) return response.memory_note
  return response.memory_saved ? 'This turn was saved.' : 'This turn was not saved.'
}
