<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'
import { cn } from '@/lib/utils'

const route = useRoute()

function linkClass(path: string) {
  const active = route.path === path
  return cn(
    'flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors',
    active
      ? 'bg-sidebar-accent text-sidebar-accent-foreground'
      : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground',
  )
}
</script>

<template>
  <div class="flex h-full flex-col gap-4 p-4">
    <div class="flex items-center justify-between">
      <div class="text-sm font-semibold">AI Chat</div>
      <div class="rounded-full border px-2 py-0.5 text-[10px] text-sidebar-foreground/70">
        V1
      </div>
    </div>

    <nav class="flex flex-col gap-1">
      <RouterLink :class="linkClass('/chat')" to="/chat">Chat</RouterLink>
      <RouterLink :class="linkClass('/files')" to="/files">Files (RAG)</RouterLink>
      <RouterLink :class="linkClass('/settings')" to="/settings">Settings</RouterLink>
    </nav>

    <div class="mt-auto text-xs text-sidebar-foreground/60">
      Workspace chat with knowledge and tools.
    </div>
  </div>
</template>
