<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'

const props = defineProps<{
  status?: string | null
  verified?: boolean
}>()

const kind = computed(() => {
  if (props.verified === true) return 'verified'
  if (props.verified === false) return 'not_verified'
  const value = (props.status || 'not_verified').toLowerCase()
  if (value === 'verified') return 'verified'
  if (value === 'unknown') return 'unknown'
  return 'not_verified'
})

const label = computed(() => {
  if (kind.value === 'verified') return 'Verified'
  if (kind.value === 'unknown') return 'Unknown'
  return 'Not verified'
})
</script>

<template>
  <Badge
    :variant="kind === 'verified' ? 'default' : 'outline'"
    :class="kind === 'unknown' ? 'border-brand-amber text-foreground' : ''"
  >
    {{ label }}
  </Badge>
</template>
