<script setup lang="ts">
import { computed } from 'vue'
import { Check, Circle, Loader2, X } from 'lucide-vue-next'
import type { AgentRun } from '@/lib/chat'

const props = defineProps<{ run: AgentRun }>()
const terminal = computed(() => ['completed', 'partial', 'failed', 'cancelled', 'budget_exceeded'].includes(props.run.status))
function statusFor(index: number) {
  return props.run.steps.find(item => item.step_index === index)?.status ?? 'pending'
}
function duration(ms: number | null | undefined) {
  return ms == null ? '未知' : `${(ms / 1000).toFixed(3)} s`
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
    <details v-if="run.metrics" class="mt-4 border-t border-white/10 pt-3 text-xs text-white/55">
      <summary class="cursor-pointer">运行指标 · {{ run.metrics.finished ? '已结束' : '采集中' }}</summary>
      <dl class="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
        <div><dt>总运行耗时</dt><dd>{{ duration(run.metrics.duration_ms) }}</dd></div>
        <div><dt>首段可见文本 TTFT</dt><dd>{{ duration(run.metrics.ttft_ms) }}</dd></div>
        <div><dt>模型调用次数</dt><dd>{{ run.metrics.model_call_count }}</dd></div>
        <div><dt>模型调用耗时</dt><dd>{{ duration(run.metrics.model_duration_ms) }}</dd></div>
        <div><dt>工具累计耗时</dt><dd>{{ duration(run.metrics.tool_duration_ms) }}</dd></div>
        <div><dt>总 Token</dt><dd>{{ run.metrics.usage?.total_tokens ?? '未知' }}</dd></div>
        <div><dt>输入 / 输出 Token</dt><dd>{{ run.metrics.usage ? `${run.metrics.usage.prompt_tokens} / ${run.metrics.usage.completion_tokens}` : '未知' }}</dd></div>
        <div><dt>费用（USD）</dt><dd>{{ run.metrics.cost_usd == null ? '未知' : run.metrics.cost_usd }}</dd></div>
        <div><dt>预算计数{{ run.metrics.budget_tokens_estimated ? '（含估算）' : '' }}</dt><dd>{{ run.metrics.budget_tokens }}</dd></div>
      </dl>
      <ul v-if="run.metrics.tools.length" class="mt-3 space-y-1" aria-label="工具耗时">
        <li v-for="tool in run.metrics.tools" :key="tool.step_index">#{{ tool.step_index }} {{ tool.name }} · {{ duration(tool.duration_ms) }} · {{ tool.status }}<span v-if="tool.error_type"> · {{ tool.error_type }}</span></li>
      </ul>
      <ul v-if="run.metrics.model_calls.length" class="mt-3 space-y-1" aria-label="模型调用耗时">
        <li v-for="call in run.metrics.model_calls" :key="call.index">#{{ call.index }} {{ call.stage }} · {{ duration(call.duration_ms) }} · {{ call.status }}<span v-if="call.error_type"> · {{ call.error_type }}</span></li>
      </ul>
      <p v-if="run.metrics.failure_type" class="mt-3 text-amber-200/75">终止阶段：{{ run.metrics.failure_stage }} · {{ run.metrics.failure_type }}</p>
    </details>
    <p v-else class="mt-3 text-xs text-white/35">暂无运行指标</p>
    <p v-if="terminal && run.error" class="mt-3 text-xs text-amber-200/75">{{ run.error }}</p>
  </aside>
</template>
