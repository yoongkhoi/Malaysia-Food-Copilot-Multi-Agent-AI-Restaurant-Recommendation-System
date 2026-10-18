<script setup lang="ts">
defineProps<{ message: string }>()
</script>

<template>
  <div class="rounded-lg border border-destructive/30 bg-card px-4 py-3 text-sm text-destructive" role="alert">
    {{ message }}
  </div>
</template>
