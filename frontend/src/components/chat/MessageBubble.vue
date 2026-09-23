<script setup lang="ts">
import { computed, ref } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { cn } from '@/lib/utils'
import type { UiChatMessage } from '@/lib/chat'
import AttachmentChips from '@/components/chat/AttachmentChips.vue'

const props = defineProps<{ message: UiChatMessage; typing?: boolean }>()

const isUser = computed(() => props.message.role === 'user')
const isAssistant = computed(() => props.message.role === 'assistant')
const failedCharts = ref(new Set<string>())
function markChartFailed(url: string) { failedCharts.value = new Set([...failedCharts.value, url]) }
const renderedContent = computed(() =>
  DOMPurify.sanitize(marked.parse(props.message.content, { async: false })),
)
</script>

<template>
  <div :class="cn('message-enter flex flex-col gap-2', isUser ? 'items-end' : 'items-start')">
    <div
      :class="
        cn(
          'text-[15px] leading-7',
          isUser && 'max-w-[85%] whitespace-pre-wrap rounded-[20px] bg-[#20242b] px-5 py-3 text-white/90 sm:max-w-[75%]',
          isAssistant && 'w-full min-w-0 text-white/85',
          !isUser && !isAssistant && 'bg-card text-foreground border',
        )
      "
    >
      <template v-if="typing">
        <div class="flex items-center gap-1 py-1">
          <span class="inline-block size-2 rounded-full bg-foreground/60 animate-bounce" style="animation-delay: 0ms" />
          <span class="inline-block size-2 rounded-full bg-foreground/60 animate-bounce" style="animation-delay: 120ms" />
          <span class="inline-block size-2 rounded-full bg-foreground/60 animate-bounce" style="animation-delay: 240ms" />
        </div>
      </template>
      <template v-else>
        <div v-if="isAssistant" class="markdown-body" v-html="renderedContent" />
        <template v-else>{{ message.content }}</template>
      </template>
    </div>

    <AttachmentChips v-if="message.attachments?.length" :attachments="message.attachments" />
    <div v-if="message.charts?.length" class="grid w-full gap-3 pt-2 sm:grid-cols-2">
      <figure v-for="chart in message.charts" :key="chart.url" class="overflow-hidden rounded-xl border border-white/10 bg-white/[0.035]">
        <div v-if="failedCharts.has(chart.url)" class="flex min-h-32 items-center justify-center px-4 text-center text-xs text-white/45">Chart could not be loaded.</div>
        <img v-else :src="chart.url" :alt="chart.title" class="h-auto max-h-[32rem] w-full object-contain" loading="lazy" @error="markChartFailed(chart.url)" />
        <figcaption class="px-3 py-2 text-xs text-white/55">{{ chart.title }}</figcaption>
      </figure>
    </div>
    <div v-if="message.sources?.length" class="w-full pt-2 text-xs text-white/45">
      <div class="mb-2 font-medium tracking-wide">Sources</div>
      <div class="flex flex-wrap gap-2">
        <template v-for="(source, index) in message.sources" :key="`${source.url ?? source.document_id}:${source.chunk_index}:${index}`">
        <a v-if="source.type === 'web' && source.url" :href="source.url" target="_blank" rel="noopener noreferrer"
          class="source-chip max-w-full truncate rounded-xl border border-white/10 bg-white/[0.035] px-3 py-1.5 text-white/65 hover:text-white/90"
          :title="source.url">🌐 {{ source.title || source.url }}</a>
        <details v-else
          class="source-chip group max-w-full rounded-xl border border-white/10 bg-white/[0.035] text-white/65 open:w-full open:max-w-xl">
          <summary class="cursor-pointer truncate px-3 py-1.5 marker:text-white/30 hover:text-white/90">
            📄 {{ source.filename }} · Chunk {{ source.chunk_index }}
          </summary>
          <p class="border-t border-white/10 px-3 py-2 leading-relaxed whitespace-pre-wrap text-white/55">{{ source.content_preview }}</p>
        </details>
        </template>
      </div>
    </div>
    <div v-if="message.usage" class="text-xs text-muted-foreground">
      {{ message.usage.total_tokens }} tokens
    </div>
  </div>
</template>

<style scoped>
.message-enter { animation: message-in 170ms ease-out both; }
@keyframes message-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (prefers-reduced-motion: reduce) { .message-enter { animation: none; } }
.markdown-body { overflow-wrap: anywhere; }
.markdown-body :deep(h1) { font-size: 1.45rem; font-weight: 650; line-height: 1.3; }
.markdown-body :deep(h2) { font-size: 1.2rem; font-weight: 600; line-height: 1.4; }
.markdown-body :deep(h3) { font-size: 1.05rem; font-weight: 600; }
.markdown-body :deep(a) { color: #bdcde7; text-decoration: underline; text-underline-offset: 3px; }
.markdown-body :deep(code) { border-radius: 4px; background: #ffffff12; padding: .12rem .3rem; font-size: .9em; }
.markdown-body :deep(pre) { overflow-x: auto; border: 1px solid #ffffff14; border-radius: 12px; background: #11141a; padding: 1rem; margin: .75rem 0 1rem; line-height: 1.55; }
.markdown-body :deep(pre code) { background: transparent; padding: 0; }
.markdown-body :deep(blockquote) { margin: .75rem 0; border-left: 2px solid #ffffff45; padding-left: 1rem; color: #ffffff9c; }
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(p),
.markdown-body :deep(ul),
.markdown-body :deep(ol),
.markdown-body :deep(table) {
  margin: 0 0 0.75rem;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 1.25rem;
}

.markdown-body :deep(ul) { list-style: disc; }
.markdown-body :deep(ol) { list-style: decimal; }
.markdown-body :deep(table) { border-collapse: collapse; }
.markdown-body :deep(th),
.markdown-body :deep(td) { border: 1px solid #ffffff24; padding: 0.35rem 0.6rem; }
.markdown-body :deep(:last-child) { margin-bottom: 0; }
</style>
