import { defineStore } from 'pinia'
import { ref } from 'vue'

function stored(key: string) {
  const existing = localStorage.getItem(key)
  if (existing) return existing
  const created = crypto.randomUUID()
  localStorage.setItem(key, created)
  return created
}

export const useSessionStore = defineStore('session', () => {
  const userId = ref(stored('mfc-user-id'))
  const sessionId = ref(stored('mfc-session-id'))

  function newSession() {
    sessionId.value = crypto.randomUUID()
    localStorage.setItem('mfc-session-id', sessionId.value)
  }

  return { userId, sessionId, newSession }
})
