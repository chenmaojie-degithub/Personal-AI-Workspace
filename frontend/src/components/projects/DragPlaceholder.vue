<script setup lang="ts">
defineProps<{ depth: number; height: number; valid: boolean }>()
</script>

<template>
  <div class="pointer-events-none relative z-10 h-0" :style="{ marginLeft: `${depth * 14 + 4}px` }" aria-hidden="true">
    <div class="absolute -top-px left-0 right-2 h-0.5 rounded-full transition-colors"
      :class="valid ? 'bg-sky-300/80 shadow-[0_0_8px_rgba(125,211,252,.45)]' : 'bg-red-400/80'" />
  </div>
</template>
