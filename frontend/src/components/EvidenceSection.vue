<script setup lang="ts">
import type { RestaurantEvidence } from '@/types/api'
import StatusBadge from '@/components/StatusBadge.vue'

defineProps<{ evidence: RestaurantEvidence }>()
</script>

<template>
  <section class="space-y-4">
    <div>
      <p class="font-mono text-xs text-muted-foreground">{{ evidence.restaurant_id }}</p>
      <h2 class="mt-1 text-3xl">Stored evidence</h2>
    </div>
    <dl class="grid gap-3 sm:grid-cols-2">
      <div class="rounded-lg border border-border bg-card p-4">
        <dt class="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Address</dt>
        <dd class="mt-2 text-sm">{{ evidence.address || 'No street address is stored.' }}</dd>
        <div class="mt-3"><StatusBadge :verified="evidence.location_verified" /></div>
        <p class="mt-2 text-xs text-muted-foreground">Location evidence: {{ evidence.location_evidence || 'none' }}</p>
      </div>
      <div class="rounded-lg border border-border bg-card p-4">
        <dt class="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Price</dt>
        <dd class="mt-2 text-sm">
          <template v-if="evidence.price_status === 'verified' && evidence.price_max_myr != null">
            Up to RM{{ evidence.price_max_myr }}
          </template>
          <template v-else>No verified price range is stored.</template>
        </dd>
        <div class="mt-3"><StatusBadge :status="evidence.price_status" /></div>
      </div>
      <div class="rounded-lg border border-border bg-card p-4 sm:col-span-2">
        <dt class="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Halal</dt>
        <dd class="mt-2 text-sm">
          <a
            v-if="evidence.halal_status === 'verified' && evidence.halal_source_url"
            class="underline underline-offset-4"
            :href="evidence.halal_source_url"
            target="_blank"
            rel="noreferrer"
          >{{ evidence.halal_source_url }}</a>
          <template v-else>No branch-specific halal source is stored. Not verified is not a claim that the restaurant is non-halal.</template>
        </dd>
        <div class="mt-3"><StatusBadge :status="evidence.halal_status" /></div>
      </div>
    </dl>
    <ul v-if="evidence.evidence.length" class="space-y-2">
      <li v-for="item in evidence.evidence" :key="`${item.claim}-${item.source_url}`" class="text-sm">
        <span class="font-medium">{{ item.claim }}</span>
        <a class="ml-2 underline underline-offset-4" :href="item.source_url" target="_blank" rel="noreferrer">{{ item.source_url }}</a>
      </li>
    </ul>
    <p v-else class="text-sm text-muted-foreground">No source URLs are attached to this record.</p>
  </section>
</template>
