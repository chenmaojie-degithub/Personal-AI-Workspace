<script setup lang="ts">
import type { UiAttachment } from '@/lib/chat'
import { AlertTriangle, CheckCircle2, FileText, Loader2, X } from 'lucide-vue-next'

defineProps<{
  attachments: UiAttachment[]
  removable?: boolean
}>()

const emit = defineEmits<{
  (e: 'remove', id: string): void
}>()

function uploadedLabel(filename: string) {
  return /\.(csv|xlsx)$/i.test(filename) ? 'Ready' : 'Indexed'
}
</script>

<template>
  <div class="flex flex-wrap gap-2">
    <div
      v-for="a in attachments"
      :key="a.id"
      class="attachment-chip inline-flex max-w-full items-center gap-2 rounded-full border border-white/10 bg-white/[0.06] px-3 py-1.5 text-xs text-white/70"
      :class="
        a.status === 'uploaded'
          ? 'text-emerald-200/85'
          : a.status === 'warning'
            ? 'text-amber-200/85'
            : a.status === 'error'
              ? 'text-red-300'
              : 'text-white/55'
      "
      :title="a.detail || a.filename"
    >
      <Loader2 v-if="a.status === 'uploading'" class="size-3.5 animate-spin" />
      <CheckCircle2 v-else-if="a.status === 'uploaded'" class="size-3.5" />
      <AlertTriangle v-else-if="a.status === 'warning' || a.status === 'error'" class="size-3.5" />
      <FileText v-else class="size-3.5" />

      <span class="max-w-56 truncate font-medium">{{ a.filename }}</span>
      <span class="hidden text-[10px] opacity-65 sm:inline">{{ a.status === 'uploaded' ? uploadedLabel(a.filename) : a.status === 'uploading' ? 'Uploading...' : a.status === 'warning' ? 'Not indexed' : 'Failed' }}</span>

      <button
        v-if="removable"
        type="button"
        class="rounded-full p-0.5 hover:bg-white/10"
        :title="`Remove ${a.filename}`"
        @click="emit('remove', a.id)"
      >
        <X class="size-3.5" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.attachment-chip { animation: attachment-in 160ms ease-out both; }
@keyframes attachment-in { from { opacity: 0; transform: scale(.98); } to { opacity: 1; transform: scale(1); } }
@media (prefers-reduced-motion: reduce) { .attachment-chip { animation: none; } }
</style>
