<script setup lang="ts">
defineProps<{
  title: string
  description: string
}>()
</script>

<template>
  <div class="rounded-2xl border border-dashed border-primary/30 bg-card px-6 py-12 shadow-sm">
    <h2 class="text-2xl">{{ title }}</h2>
    <p class="mt-2 max-w-2xl text-sm leading-6 whitespace-pre-wrap text-muted-foreground">{{ description }}</p>
  </div>
</template>
