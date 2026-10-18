<script setup lang="ts">
import type { RestaurantResult } from '@/types/api'
import { evidenceLines } from '@/lib/evidence'

defineProps<{
  restaurant: RestaurantResult
  selected?: boolean
}>()

defineEmits<{ select: [] }>()
</script>

<template>
  <button
    type="button"
    class="w-full rounded-2xl border bg-card p-4 text-left shadow-sm transition hover:-translate-y-px hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    :class="selected ? 'border-primary ring-2 ring-primary/20' : 'border-border'"
    @click="$emit('select')"
  >
    <div class="flex gap-4">
      <img
        v-if="restaurant.photo_url"
        :src="restaurant.photo_url"
        alt=""
        class="size-16 shrink-0 rounded-md object-cover"
      />
      <div v-else class="flex size-16 shrink-0 items-center justify-center rounded-xl bg-accent px-1 text-center text-[10px] leading-tight font-medium text-accent-foreground">
        No confirmed photo
      </div>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <h3 class="font-heading text-xl leading-snug">{{ restaurant.name || 'Unnamed restaurant' }}</h3>
          <span v-if="restaurant.cuisine_label" class="rounded-full bg-secondary px-2 py-0.5 text-[11px] text-secondary-foreground">{{ restaurant.cuisine_label }}</span>
        </div>
        <p class="mt-1 text-sm text-muted-foreground">
          {{ restaurant.stored_address || 'Street address is not on file' }}
        </p>
        <p v-if="restaurant.match_reason" class="mt-2 text-xs leading-5 text-muted-foreground">{{ restaurant.match_reason }}</p>
        <details class="mt-2">
          <summary class="cursor-pointer text-xs text-primary">Record details</summary>
          <p
            v-for="line in evidenceLines(restaurant)"
            :key="line"
            class="mt-1 text-xs text-muted-foreground"
          >
            {{ line }}
          </p>
        </details>
        <a
          v-if="restaurant.map_url"
          :href="restaurant.map_url"
          target="_blank"
          rel="noreferrer"
          class="mt-3 inline-block text-sm font-medium text-primary underline-offset-4 hover:underline"
          @click.stop
        >Open this pin on OpenStreetMap</a>
      </div>
    </div>
  </button>
</template>
