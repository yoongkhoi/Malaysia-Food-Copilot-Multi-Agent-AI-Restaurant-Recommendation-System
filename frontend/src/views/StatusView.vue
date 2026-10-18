<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Button } from '@/components/ui/button'
import ErrorState from '@/components/ErrorState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { health, memoryStatus, opsBoard, request } from '@/lib/api'
import type { HealthStatus, MemoryStatus } from '@/types/api'

interface TableStat { name: string, rows: number, bytes: number }
interface RecentMessage { session_id: string, role: string, content: string, created_at: string }
interface RedisSession { session_id: string, messages: number, ttl_seconds: number }
interface Board {
  postgres?: {
    connected: boolean
    database_bytes: number | null
    quota: string
    tables: TableStat[]
    recent_messages: RecentMessage[]
    error: string | null
  }
  redis?: {
    connected: boolean
    used_memory_bytes: number | null
    used_memory_dataset_bytes?: number | null
    db_keys?: number
    memory_note?: string
    session_keys: number
    sessions: RedisSession[]
    error: string | null
  }
  restaurants?: { source: string, records: number, discovered: number, stored_in: string }
}

const api = ref<HealthStatus | null>(null)
const memory = ref<MemoryStatus | null>(null)
const board = ref<Board | null>(null)
const apiError = ref('')
const memoryError = ref('')
const boardError = ref('')

function bytes(value: number | null | undefined) {
  if (value === null || value === undefined) return '无法从当前接口获取'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

const restaurantQuery = ref('')
const restaurantPage = ref<{ total: number, restaurants: { restaurant_id: string, name: string | null, cuisine: string[], regions: string[], address: string | null, latitude: number | null, longitude: number | null }[] } | null>(null)
const opsMessage = ref('')
const clearing = ref(false)
const refreshing = ref(false)

async function searchRestaurants() {
  opsMessage.value = ''
  try {
    restaurantPage.value = await request('/api/ops/restaurants?q=' + encodeURIComponent(restaurantQuery.value) + '&limit=20')
  } catch (caught) {
    opsMessage.value = caught instanceof Error ? caught.message : 'Restaurant search failed.'
  }
}

async function clearSessions() {
  if (!window.confirm('Delete chat sessions in Neon and Redis? Restaurant records stay.')) return
  if (!window.confirm('This cannot be undone. Type of data: messages, conversations, and session keys.')) return
  clearing.value = true
  opsMessage.value = 'Clearing sessions…'
  try {
    const result = await request<{ redis_keys: number, messages: number, conversations: number }>('/api/ops/clear-sessions', {
      method: 'POST',
      body: JSON.stringify({ confirm: 'clear-sessions' }),
    })
    opsMessage.value = `Cleared ${result.messages} messages, ${result.conversations} conversations, ${result.redis_keys} Redis keys.`
    await loadBoard()
  } catch (caught) {
    opsMessage.value = caught instanceof Error ? caught.message : 'Clear failed.'
  } finally {
    clearing.value = false
  }
}

async function loadBoard() {
  boardError.value = ''
  refreshing.value = true
  try {
    board.value = await opsBoard() as Board
  } catch (caught) {
    boardError.value = caught instanceof Error ? caught.message : 'The database board is unreachable.'
  } finally {
    refreshing.value = false
  }
}

onMounted(async () => {
  try {
    api.value = await health()
  } catch (caught) {
    apiError.value = caught instanceof Error ? caught.message : 'The API is unreachable.'
  }
  try {
    memory.value = await memoryStatus()
  } catch (caught) {
    memoryError.value = caught instanceof Error ? caught.message : 'Memory status is unreachable.'
  }
  await loadBoard()
})
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      eyebrow="System Status"
      title="Neon, Redis, and the restaurant file."
      description="Counts and recent rows come from the configured stores. Connection strings stay on the server. Restaurant records are the JSON file, not a Neon table."
    />
    <div class="flex justify-end gap-2">
      <Button type="button" variant="outline" :disabled="clearing || refreshing" @click="clearSessions">
        {{ clearing ? 'Clearing sessions…' : 'Clear sessions' }}
      </Button>
      <Button type="button" variant="outline" :disabled="clearing || refreshing" @click="loadBoard">
        {{ refreshing ? 'Refreshing board…' : 'Refresh board' }}
      </Button>
    </div>
    <p v-if="clearing || refreshing" class="text-sm text-muted-foreground" role="status">
      {{ clearing ? 'Clearing sessions…' : 'Refreshing the database board…' }}
    </p>
    <p v-if="opsMessage" class="text-sm">{{ opsMessage }}</p>
    <ErrorState v-if="boardError" :message="boardError" />
    <div class="grid gap-4 lg:grid-cols-2">
      <section class="rounded-2xl border border-border bg-card p-5 shadow-sm">
        <h2 class="text-2xl">Neon Postgres</h2>
        <dl v-if="board?.postgres" class="mt-3 space-y-1 text-sm">
          <div>Connected: {{ board.postgres.connected ? 'yes' : 'no' }}</div>
          <div>Error: {{ board.postgres.error || 'none' }}</div>
          <div>Whole database size: {{ bytes(board.postgres.database_bytes) }}</div>
          <div>Provider quota: {{ board.postgres.quota }}</div>
        </dl>
        <table v-if="board?.postgres?.tables.length" class="mt-4 w-full text-left text-sm">
          <thead>
            <tr class="border-b border-border">
              <th class="py-1">Table</th>
              <th>Rows</th>
              <th>This table</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="table in board.postgres.tables" :key="table.name" class="border-b border-border">
              <td class="py-1 font-mono">{{ table.name }}</td>
              <td>{{ table.rows }}</td>
              <td>{{ bytes(table.bytes) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
      <section class="rounded-2xl border border-border bg-card p-5 shadow-sm">
        <h2 class="text-2xl">Redis</h2>
        <dl v-if="board?.redis" class="mt-3 space-y-1 text-sm">
          <div>Connected: {{ board.redis.connected ? 'yes' : 'no' }}</div>
          <div>Error: {{ board.redis.error || 'none' }}</div>
          <div>Redis process memory: {{ bytes(board.redis.used_memory_bytes) }}</div>
          <div>Dataset bytes inside that process: {{ bytes(board.redis.used_memory_dataset_bytes) }}</div>
          <div>Keys in this Redis database: {{ board.redis.db_keys ?? 'unknown' }}</div>
          <div>This app's session message keys: {{ board.redis.session_keys }}</div>
          <p class="mt-2 text-xs text-muted-foreground">{{ board.redis.memory_note }}</p>
        </dl>
        <ul class="mt-4 space-y-2 text-xs">
          <li v-for="item in board?.redis?.sessions || []" :key="item.session_id" class="rounded border border-border p-2 font-mono">
            {{ item.session_id }} · {{ item.messages }} messages · TTL {{ item.ttl_seconds }}s
          </li>
        </ul>
      </section>
    </div>
    <section class="rounded-2xl border border-border bg-card p-5 shadow-sm">
      <h2 class="text-2xl">Recent Neon messages</h2>
      <p class="mt-1 text-xs text-muted-foreground">Latest 12 rows. Content is clipped. This is the change list, not an editor for restaurant facts.</p>
      <ul class="mt-3 space-y-2 text-sm">
        <li v-for="(item, index) in board?.postgres?.recent_messages || []" :key="index" class="rounded border border-border p-2">
          <span class="font-mono text-xs">{{ item.created_at }} · {{ item.role }} · {{ item.session_id }}</span>
          <p class="mt-1">{{ item.content }}</p>
        </li>
      </ul>
    </section>
    <section class="rounded-2xl border border-border bg-card p-5 shadow-sm text-sm">
      <h2 class="text-2xl">Restaurant file</h2>
      <p class="mt-3">{{ board?.restaurants?.source }}</p>
      <p>Records: {{ board?.restaurants?.records ?? 'unknown' }}. Discovered sidecar: {{ board?.restaurants?.discovered ?? 'unknown' }}.</p>
      <p>{{ board?.restaurants?.stored_in }}</p>
      <form class="mt-4 flex gap-2" @submit.prevent="searchRestaurants">
        <input v-model="restaurantQuery" class="flex-1 rounded-md border border-border bg-background px-3 py-2" placeholder="Search name, cuisine, or region" />
        <Button type="submit" variant="outline">Search</Button>
      </form>
      <p v-if="restaurantPage" class="mt-2 text-xs text-muted-foreground">{{ restaurantPage.total }} matches, showing {{ restaurantPage.restaurants.length }}. The same brand at a different coordinate is a separate branch, not a copied row.</p>
      <ul class="mt-2 space-y-2 text-sm">
        <li v-for="row in restaurantPage?.restaurants || []" :key="row.restaurant_id">
          <p>{{ row.name || 'Unnamed' }} · {{ row.cuisine.join(', ') || 'type unknown' }} · {{ row.regions.join(', ') }}</p>
          <p class="text-xs text-muted-foreground">
            {{ row.address || 'No street address on this OSM row' }}
            <span v-if="row.latitude != null && row.longitude != null"> · {{ row.latitude.toFixed(5) }}, {{ row.longitude.toFixed(5) }}</span>
          </p>
        </li>
      </ul>
    </section>
    <div class="grid gap-4 md:grid-cols-2">
      <section class="rounded-2xl border border-border bg-card p-5 shadow-sm">
        <h2 class="text-2xl">API</h2>
        <ErrorState v-if="apiError" class="mt-3" :message="apiError" />
        <dl v-else-if="api" class="mt-3 space-y-1 text-sm">
          <div>Status: {{ api.status }}</div>
          <div>Pilot: {{ api.pilot }}</div>
          <div>Expansion: {{ api.expansion }}</div>
          <div>Dataset: {{ api.dataset || 'not reported' }} ({{ api.dataset_records ?? 'unknown' }} records)</div>
          <div>Retrieval: {{ api.retrieval || 'not reported' }}</div>
          <div>LLM agent: {{ api.llm_agent ? 'on' : 'off' }}</div>
          <div>LangGraph: {{ api.langgraph ? 'on' : 'off' }}</div>
          <div>Web search: {{ api.web_search ? 'configured for this process' : 'off' }}</div>
        </dl>
      </section>
      <section class="rounded-2xl border border-border bg-card p-5 shadow-sm">
        <h2 class="text-2xl">Memory flags</h2>
        <ErrorState v-if="memoryError" class="mt-3" :message="memoryError" />
        <dl v-else-if="memory" class="mt-3 space-y-1 text-sm">
          <div>Postgres configured: {{ memory.postgres ? 'yes' : 'no' }}</div>
          <div>Redis configured: {{ memory.redis ? 'yes' : 'no' }}</div>
        </dl>
      </section>
    </div>
  </div>
</template>
