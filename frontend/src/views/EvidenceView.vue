<script setup lang="ts">
import { ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import EvidenceSection from '@/components/EvidenceSection.vue'
import PageHeader from '@/components/PageHeader.vue'
import { Skeleton } from '@/components/ui/skeleton'
import { restaurantEvidence } from '@/lib/api'
import type { RestaurantEvidence } from '@/types/api'

const restaurantId = ref('')
const loading = ref(false)
const error = ref('')
const evidence = ref<RestaurantEvidence | null>(null)

async function lookup() {
  const id = restaurantId.value.trim()
  if (!id) return
  loading.value = true
  error.value = ''
  evidence.value = null
  try {
    evidence.value = await restaurantEvidence(id)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'This restaurant could not be loaded.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Restaurant Evidence"
      title="Verified, not verified, and unknown stay separate."
      description="A missing source is never shown as verified. The page reads the stored record for the exact restaurant id."
    />
    <form class="flex max-w-xl flex-col gap-3 sm:flex-row sm:items-end" @submit.prevent="lookup">
      <div class="flex-1">
        <Label for="restaurant-id">Restaurant ID</Label>
        <Input id="restaurant-id" v-model="restaurantId" class="mt-2" placeholder="MY-OSM-node-..." />
      </div>
      <Button type="submit" :disabled="loading">Look up</Button>
    </form>
    <Skeleton v-if="loading" class="mt-6 h-40 w-full" />
    <ErrorState v-else-if="error" class="mt-6" :message="error" />
    <EvidenceSection v-else-if="evidence" class="mt-6" :evidence="evidence" />
    <EmptyState v-else class="mt-6" title="Look up one restaurant" description="Enter an exact ID from a search result. Unknown ids return a not-found error instead of a guessed restaurant." />
  </div>
</template>
