<script setup lang="ts">
defineProps<{
  eyebrow: string
  title: string
  description: string
}>()
</script>

<template>
  <header class="mb-8 max-w-3xl">
    <p class="text-xs font-semibold tracking-[0.16em] text-primary uppercase">{{ eyebrow }}</p>
    <h1 class="mt-2 text-4xl leading-[1.1] text-balance sm:text-5xl">{{ title }}</h1>
    <p class="mt-3 text-base leading-7 text-muted-foreground">{{ description }}</p>
  </header>
</template>
