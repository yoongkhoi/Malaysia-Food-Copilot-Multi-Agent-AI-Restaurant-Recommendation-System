<script setup lang="ts">
import { ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import PageHeader from '@/components/PageHeader.vue'
import RestaurantCard from '@/components/RestaurantCard.vue'
import { discover } from '@/lib/api'
import { buildDiscoveryQuery } from '@/lib/search'
import type { DiscoveryResponse } from '@/types/api'

const text = ref('Korean BBQ')
const loading = ref(false)
const error = ref('')
const outcome = ref<DiscoveryResponse | null>(null)
const sentQuery = ref('')

async function search() {
  error.value = ''
  const query = buildDiscoveryQuery({ text: text.value })
  sentQuery.value = query
  loading.value = true
  try {
    outcome.value = await discover(query)
  } catch (caught) {
    outcome.value = null
    error.value = caught instanceof Error ? caught.message : 'The search failed.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Discover"
      title="Find a restaurant by place, cuisine, or occasion."
      description="Searches Old Klang Road. A missing price is left blank. Halal status is not required unless you ask for a certified restaurant."
    />
    <form class="max-w-3xl space-y-4 rounded-2xl border border-border bg-card p-5 shadow-sm" @submit.prevent="search">
      <div>
        <Label for="request">What do you want?</Label>
        <Textarea id="request" v-model="text" class="mt-2" rows="3" placeholder="Korean BBQ, a mamak for supper, a cafe for a date" />
      </div>
      <Button type="submit" :disabled="loading">{{ loading ? 'Searching…' : 'Search' }}</Button>
    </form>
    <p v-if="sentQuery" class="mt-4 text-xs text-muted-foreground">Query: {{ sentQuery }}</p>
    <ErrorState v-if="error" class="mt-4" :message="error" />
    <EmptyState
      v-else-if="outcome && outcome.results.length === 0"
      class="mt-6"
      title="No matching restaurant in the current records"
      :description="outcome.answer"
    />
    <div v-else-if="outcome" class="mt-6 max-w-3xl space-y-3">
      <p class="rounded-2xl border border-border bg-card p-5 text-sm leading-7 whitespace-pre-wrap shadow-sm">{{ outcome.answer }}</p>
      <RestaurantCard v-for="restaurant in outcome.results" :key="restaurant.restaurant_id" :restaurant="restaurant" />
    </div>
  </div>
</template>
