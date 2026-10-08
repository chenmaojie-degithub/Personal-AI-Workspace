<script setup lang="ts">
import { computed } from 'vue'
import { Check, Circle, Loader2, X } from 'lucide-vue-next'
import type { AgentRun } from '@/lib/chat'

const props = defineProps<{ run: AgentRun }>()
const terminal = computed(() => ['completed', 'failed', 'cancelled', 'budget_exceeded'].includes(props.run.status))
function statusFor(index: number) {
  return props.run.steps.find(item => item.step_index === index)?.status ?? 'pending'
}
</script>

<template>
  <aside class="mb-6 rounded-2xl border border-white/10 bg-white/[.025] p-4 text-sm text-white/70" aria-live="polite">
    <div class="flex items-center justify-between gap-3">
      <div class="min-w-0"><div class="text-[10px] uppercase tracking-[.18em] text-white/35">Agent task</div><div class="mt-1 truncate text-white/85">{{ run.goal }}</div></div>
      <span class="shrink-0 rounded-full border border-white/10 px-2.5 py-1 text-[11px] capitalize">{{ run.status.replace('_', ' ') }}</span>
    </div>
    <ol v-if="run.plan.length" class="mt-4 space-y-2">
      <li v-for="step in run.plan" :key="step.index" class="flex items-start gap-2">
        <Loader2 v-if="statusFor(step.index) === 'running'" class="mt-0.5 size-4 shrink-0 animate-spin text-sky-300" />
        <Check v-else-if="statusFor(step.index) === 'completed'" class="mt-0.5 size-4 shrink-0 text-emerald-300" />
        <X v-else-if="statusFor(step.index) === 'failed'" class="mt-0.5 size-4 shrink-0 text-red-300" />
        <Circle v-else class="mt-1 size-3 shrink-0 text-white/25" />
        <div><div>{{ step.title }}</div><div v-if="run.steps.find(item => item.step_index === step.index)?.tool_name" class="mt-0.5 text-xs text-white/35">{{ run.steps.find(item => item.step_index === step.index)?.tool_name }}</div></div>
      </li>
    </ol>
    <p v-if="terminal && run.error" class="mt-3 text-xs text-amber-200/75">{{ run.error }}</p>
  </aside>
</template>
