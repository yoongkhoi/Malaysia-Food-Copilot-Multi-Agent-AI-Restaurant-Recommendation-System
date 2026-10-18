<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import RestaurantCard from '@/components/RestaurantCard.vue'
import RestaurantMap from '@/components/RestaurantMap.vue'
import { chat, sessionList, sessionMessages } from '@/lib/api'
import { memoryStatusText } from '@/lib/memoryStatus'
import { reviewEvidenceLine } from '@/lib/reviewEvidence'
import { followUpContext } from '@/lib/search'
import { useSessionStore } from '@/stores/session'
import type { ChatResponse } from '@/types/api'

interface Turn {
  role: 'user' | 'assistant'
  content: string
  response?: ChatResponse
}

interface SavedSession {
  session_id: string
  started_at: string
  preview: string
}

const session = useSessionStore()
const suggestions = [
  'any recommendation for korean bbq around old klang road?',
  'how many kfc are there in old klang road?',
  'recommend korean and japanese restaurants in old klang road',
  'any japanese restaurant in kuala lumpur?',
]
const draft = ref('')
const turns = ref<Turn[]>([])
const sessions = ref<SavedSession[]>([])
const loading = ref(false)
const historyLoading = ref(false)
const error = ref('')
const notice = ref('')
const selected = ref<Record<number, string>>({})
const processing = computed(() => loading.value)
const transcript = ref<HTMLElement | null>(null)
const transcripts = new Map<string, Turn[]>()

function snapshot(id = session.sessionId) {
  transcripts.set(id, turns.value.map((turn) => ({ ...turn })))
}

function formatWhen(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function sameTranscript(local: Turn[], messages: { role: string, content: string }[]) {
  if (local.length !== messages.length) return false
  return local.every((turn, index) => {
    const role = messages[index].role === 'assistant' ? 'assistant' : 'user'
    return turn.role === role && turn.content === messages[index].content
  })
}

async function scrollTranscript() {
  await nextTick()
  const pane = transcript.value
  if (!pane) return
  const answers = pane.querySelectorAll<HTMLElement>('[data-role="assistant"]')
  const latest = answers[answers.length - 1]
  if (!latest) return
  pane.scrollTop += latest.getBoundingClientRect().top - pane.getBoundingClientRect().top
}

async function loadSessions() {
  try {
    const payload = await sessionList(session.userId)
    const ids = new Set(payload.sessions.map((item) => item.session_id))
    const localOnly = sessions.value.filter((item) => !ids.has(item.session_id))
    sessions.value = [...localOnly, ...payload.sessions]
  } catch {
    return
  }
}

async function loadCurrent() {
  const id = session.sessionId
  const known = transcripts.get(id)
  turns.value = known ? known.map((turn) => ({ ...turn })) : []
  selected.value = {}
  historyLoading.value = true
  try {
    const payload = await sessionMessages(session.userId, id)
    if (session.sessionId !== id) return
    const local = transcripts.get(id) || []
    if (sameTranscript(local, payload.messages)) {
      turns.value = local.map((turn) => ({ ...turn }))
      return
    }
    turns.value = payload.messages.map((item, index) => {
      const role = item.role === 'assistant' ? 'assistant' as const : 'user' as const
      const localTurn = local[index]
      if (localTurn && localTurn.role === role && localTurn.content === item.content) return { ...localTurn }
      return { role, content: item.content }
    })
    snapshot(id)
  } catch {
    if (!known) turns.value = []
  } finally {
    if (session.sessionId === id) historyLoading.value = false
    await scrollTranscript()
  }
}

onMounted(async () => {
  await loadSessions()
  await loadCurrent()
})

watch(() => session.sessionId, async () => {
  notice.value = `Session ${session.sessionId.slice(0, 8)}`
  await loadCurrent()
})

function onDraftKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

function askSuggestion(text: string) {
  if (loading.value) return
  draft.value = text
  send()
}

async function send() {
  const query = draft.value.trim()
  if (query.length < 2 || loading.value) return
  error.value = ''
  notice.value = ''
  turns.value.push({ role: 'user', content: query })
  draft.value = ''
  loading.value = true
  if (!sessions.value.some((item) => item.session_id === session.sessionId)) {
    sessions.value = [{
      session_id: session.sessionId,
      started_at: new Date().toISOString(),
      preview: query,
    }, ...sessions.value]
  }
  try {
    const context = followUpContext(turns.value)
    const response = await chat(query, session.userId, session.sessionId, context)
    const index = turns.value.length
    turns.value.push({ role: 'assistant', content: response.answer, response })
    if (response.results[0]) selected.value[index] = response.results[0].restaurant_id
    snapshot()
    await scrollTranscript()
    await loadSessions()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'The request failed.'
  } finally {
    loading.value = false
  }
}

async function openSession(sessionId: string) {
  if (sessionId === session.sessionId) {
    await loadCurrent()
    return
  }
  snapshot()
  session.sessionId = sessionId
  localStorage.setItem('mfc-session-id', sessionId)
}

function stageText(stages: Record<string, number> | undefined) {
  if (!stages) return ''
  const parts = Object.entries(stages).map(([name, ms]) => `${name} ${ms}ms`)
  return parts.length ? `Stages: ${parts.join(', ')}.` : ''
}

function startNewSession() {
  snapshot()
  turns.value = []
  selected.value = {}
  draft.value = ''
  session.newSession()
  transcripts.set(session.sessionId, [])
  notice.value = 'New session started. This screen no longer uses the previous area or cuisine.'
}
</script>

<template>
  <div class="mx-auto grid h-full min-h-0 max-w-6xl gap-4 overflow-hidden lg:grid-cols-[15rem_1fr]">
    <aside class="min-h-0 overflow-y-auto rounded-2xl border border-border bg-card p-3 shadow-sm">
      <div class="mb-3 flex items-center justify-between gap-2">
        <h2 class="font-heading text-lg">Sessions</h2>
        <Button type="button" variant="outline" size="sm" @click="startNewSession">New</Button>
      </div>
      <p class="mb-3 text-[11px] text-muted-foreground">This chat · {{ session.sessionId.slice(0, 8) }}</p>
      <p v-if="sessions.length === 0" class="text-xs text-muted-foreground">No saved sessions for this browser yet.</p>
      <button
        v-for="item in sessions"
        :key="item.session_id"
        type="button"
        class="mb-2 block w-full rounded-xl border px-3 py-2 text-left text-xs"
        :class="item.session_id === session.sessionId ? 'border-primary bg-accent' : 'border-border hover:bg-secondary'"
        @click="openSession(item.session_id)"
      >
        <span class="line-clamp-2">{{ item.preview || item.session_id }}</span>
        <span class="mt-1 block text-[10px] text-muted-foreground">{{ formatWhen(item.started_at) }}</span>
      </button>
    </aside>
    <div class="flex h-full min-h-0 flex-col overflow-hidden">
      <p v-if="notice" class="mb-3 shrink-0 text-sm text-muted-foreground">{{ notice }}</p>
      <div
        ref="transcript"
        class="min-h-0 flex-1 overflow-y-auto pr-1"
        :class="turns.length ? 'space-y-4' : 'flex items-center justify-center'"
      >
        <EmptyState
          v-if="turns.length === 0"
          title="Ask for a cuisine, a place, or a brand"
          description="Choose an example below, or type your own question in English, 中文, or Bahasa Melayu."
        />
        <article
          v-for="(turn, index) in turns"
          :key="`${session.sessionId}-${index}`"
          :data-role="turn.role"
          class="max-w-[46rem] px-4 py-3 text-sm leading-7 whitespace-pre-wrap"
          :class="turn.role === 'user' ? 'ml-auto rounded-2xl rounded-br-md bg-primary text-primary-foreground shadow-sm' : 'rounded-2xl border border-border bg-card shadow-sm'"
        >
          <p>{{ turn.content }}</p>
          <details v-if="turn.response" class="mt-3 text-xs opacity-80">
            <summary class="cursor-pointer font-medium">How this answer was made</summary>
            <p class="mt-2 leading-5">
              Mode: {{ turn.response.agent_mode || 'deterministic' }}.
              Intent: {{ turn.response.intent || turn.response.trace?.intent || 'unknown' }}.
              Retriever: {{ turn.response.retriever }}.
              Model: {{ turn.response.model_name || 'not called' }}{{ turn.response.trace?.llm_called ? ' (called)' : ' (not called)' }}.
              {{ turn.response.model_note }}
              {{ turn.response.trace?.total_ms ? `${turn.response.trace.total_ms} ms.` : '' }}
              Tools: {{ turn.response.tools_called.length ? turn.response.tools_called.join(', ') : 'none' }}.
              <template v-if="turn.response.trace?.agents?.length">
                Agents: {{ turn.response.trace.agents.map((item) => item.name).join(' → ') }}.
              </template>
              {{ stageText(turn.response.trace?.stages) }}
              {{ turn.response.trace?.timing_note }}
              {{ memoryStatusText(turn.response) }}
            </p>
          </details>
          <p v-if="turn.response?.review_note" class="mt-2 text-xs">{{ turn.response.review_note }}</p>
          <ul v-if="turn.response?.review_evidence?.length" class="mt-2 space-y-2 text-xs">
            <li v-for="item in turn.response.review_evidence" :key="item.review_id || item.span" class="rounded border border-border p-2">
              {{ reviewEvidenceLine(item) }}
            </li>
          </ul>
          <div v-if="turn.response?.results.length" class="mt-3 space-y-3">
            <RestaurantMap
              :restaurants="turn.response.results"
              :selected-id="selected[index]"
              @select="selected[index] = $event"
            />
            <RestaurantCard
              v-for="restaurant in turn.response.results"
              :key="restaurant.restaurant_id"
              :restaurant="restaurant"
              :selected="selected[index] === restaurant.restaurant_id"
              @select="selected[index] = restaurant.restaurant_id"
            />
          </div>
        </article>
        <p v-if="historyLoading" class="text-sm text-muted-foreground" role="status">Loading this session…</p>
        <p v-if="processing" class="text-sm text-muted-foreground" role="status">Waiting for the answer…</p>
        <ErrorState v-if="error" :message="error" />
      </div>
      <form class="mt-3 shrink-0 space-y-3 rounded-2xl border border-border bg-card p-3 shadow-sm" @submit.prevent="send">
        <div v-if="turns.length === 0" class="flex flex-wrap gap-2">
          <button
            v-for="suggestion in suggestions"
            :key="suggestion"
            type="button"
            class="rounded-full border border-border bg-card px-3 py-1.5 text-left text-xs leading-5 text-foreground shadow-sm hover:border-primary hover:bg-accent disabled:opacity-50"
            :disabled="loading"
            @click="askSuggestion(suggestion)"
          >
            {{ suggestion }}
          </button>
        </div>
        <Textarea v-model="draft" rows="3" placeholder="Ask for a place, a cuisine, or a brand" @keydown="onDraftKeydown" />
        <div class="flex items-center justify-between gap-3">
          <Button type="button" variant="outline" @click="startNewSession">New session</Button>
          <Button type="submit" :disabled="loading">Send</Button>
        </div>
      </form>
    </div>
  </div>
</template>
