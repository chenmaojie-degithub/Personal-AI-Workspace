<script setup lang="ts">
defineProps<{ depth: number; height: number; valid: boolean }>()
</script>

<template>
  <div class="px-1 py-0.5" :style="{ paddingLeft: `${depth * 14 + 4}px`, height: `${height}px` }" aria-hidden="true">
    <div class="h-full rounded-md border border-dashed transition-colors"
      :class="valid ? 'border-sky-400/70 bg-sky-400/10' : 'border-red-400/60 bg-red-400/10'" />
  </div>
</template>
