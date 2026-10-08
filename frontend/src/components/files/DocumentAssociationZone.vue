<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Check, ChevronDown, ChevronUp, FileText, FolderOpen, GripVertical, Loader2, Plus, X } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import type { AgentRun } from '@/lib/chat'

type DocumentItem = { document_id: string | null; filename: string; content_type?: string | null; status: string; ingest_error?: string | null }
type Point = { x: number; y: number }
type ViewState = 'collapsed' | 'expanding' | 'expanded' | 'collapsing'

const props = defineProps<{ workspaceId: string | null; modelValue: string[]; uploading?: boolean; agentRun?: AgentRun | null }>()
const emit = defineEmits<{ 'update:modelValue': [ids: string[]]; 'request-upload': [] }>()
const documents = ref<DocumentItem[]>([])
const error = ref<string | null>(null)
const target = ref<HTMLElement | null>(null)
const pill = ref<HTMLElement | null>(null)
const card = ref<HTMLElement | null>(null)
const details = ref<HTMLElement | null>(null)
const ghostElement = ref<HTMLElement | null>(null)
const ghost = ref<{ label: string; x: number; y: number } | null>(null)
const overTarget = ref(false)
const viewState = ref<ViewState>('collapsed')
let active: DocumentItem | null = null
let path: Point[] = []
let layoutAnimation: Animation | null = null
let detailsAnimation: Animation | null = null
let transitionId = 0

const associatedDocuments = computed(() => props.modelValue.map(id => documents.value.find(item => item.document_id === id)).filter(Boolean) as DocumentItem[])
const taskActive = computed(() => ['planning', 'running'].includes(props.agentRun?.status ?? ''))
const taskComplete = computed(() => props.agentRun?.status === 'completed')
const failed = computed(() => documents.value.some(item => item.status === 'failed') || props.agentRun?.status === 'failed')
const statusLabel = computed(() => {
  if (props.uploading) return 'Uploading'
  if (taskActive.value) return 'Running'
  if (failed.value) return 'Failed'
  if (documents.value.some(item => ['uploaded', 'parsing'].includes(item.status))) return 'Parsing'
  if (taskComplete.value) return 'Completed'
  if (associatedDocuments.value.length) return 'Indexed'
  return 'No documents'
})

function apiBase() { return import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000' }
async function load() {
  if (!props.workspaceId) { documents.value = []; return }
  try {
    const response = await fetch(`${apiBase()}/files?workspace_id=${encodeURIComponent(props.workspaceId)}`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data = await response.json() as { files: DocumentItem[] }
    documents.value = data.files.filter(item => item.document_id)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Could not load documents' }
}

function reducedMotion() { return window.matchMedia('(prefers-reduced-motion: reduce)').matches }
function cancelLayoutAnimation() {
  transitionId += 1
  layoutAnimation?.cancel()
  detailsAnimation?.cancel()
  layoutAnimation = null
  detailsAnimation = null
}
async function expand() {
  cancelLayoutAnimation()
  const id = transitionId
  const origin = pill.value?.getBoundingClientRect()
  viewState.value = 'expanding'
  await nextTick()
  const element = card.value
  const destination = element?.getBoundingClientRect()
  if (!element || !origin || !destination || reducedMotion()) { if (id === transitionId) viewState.value = 'expanded'; return }
  layoutAnimation = element.animate([
    { transform: `translateX(-50%) translate(${origin.left - destination.left}px, ${origin.top - destination.top}px) scale(${origin.width / destination.width}, ${origin.height / destination.height})`, borderRadius: '999px', opacity: .72 },
    { transform: 'translateX(-50%) translate(0, 0) scale(1)', borderRadius: '18px', opacity: 1 },
  ], { duration: 260, easing: 'cubic-bezier(.2,.8,.2,1)', composite: 'replace' })
  try { await layoutAnimation.finished } catch { return }
  if (id === transitionId) { layoutAnimation = null; viewState.value = 'expanded' }
}
async function collapse() {
  cancelLayoutAnimation()
  const id = transitionId
  viewState.value = 'collapsing'
  if (!reducedMotion() && details.value) {
    detailsAnimation = details.value.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 100, easing: 'ease-out' })
    try { await detailsAnimation.finished } catch { return }
    detailsAnimation = null
  }
  if (id !== transitionId) return
  const element = card.value
  const from = element?.getBoundingClientRect()
  const destination = pill.value?.getBoundingClientRect()
  if (!element || !from || !destination || reducedMotion()) { if (id === transitionId) viewState.value = 'collapsed'; return }
  layoutAnimation = element.animate([
    { transform: 'translateX(-50%) translate(0, 0) scale(1)', borderRadius: '18px', opacity: 1 },
    { transform: `translateX(-50%) translate(${destination.left - from.left}px, ${destination.top - from.top}px) scale(${destination.width / from.width}, ${destination.height / from.height})`, borderRadius: '999px', opacity: .65 },
  ], { duration: 230, easing: 'cubic-bezier(.4,0,.2,1)', composite: 'replace' })
  try { await layoutAnimation.finished } catch { return }
  if (id === transitionId) { layoutAnimation = null; viewState.value = 'collapsed' }
}
function toggle() { if (viewState.value === 'collapsed' || viewState.value === 'collapsing') void expand(); else void collapse() }

function associated(item: DocumentItem) { return !!item.document_id && props.modelValue.includes(item.document_id) }
function add(item: DocumentItem) {
  if (item.status !== 'indexed') { error.value = `${item.filename} is not indexed yet.`; return }
  if (item.document_id && !associated(item)) emit('update:modelValue', [...props.modelValue, item.document_id])
}
function remove(id: string) { emit('update:modelValue', props.modelValue.filter(item => item !== id)) }
function contains(point: Point) { const rect = target.value?.getBoundingClientRect(); return !!rect && point.x >= rect.left && point.x <= rect.right && point.y >= rect.top && point.y <= rect.bottom }
function move(event: PointerEvent) {
  if (!active || !ghost.value) return
  const point = { x: event.clientX, y: event.clientY }
  path.push(point); ghost.value = { ...ghost.value, ...point }; overTarget.value = contains(point)
}
async function snapBack() {
  const element = ghostElement.value
  const points = [...path].reverse()
  if (element && points.length > 1 && !reducedMotion()) {
    const stride = Math.max(1, Math.floor(points.length / 24))
    const sampled = points.filter((_, index) => index % stride === 0)
    const finalPoint = points[points.length - 1]!
    if (sampled[sampled.length - 1] !== finalPoint) sampled.push(finalPoint)
    try { await element.animate(sampled.map(point => ({ left: `${point.x}px`, top: `${point.y}px` })), { duration: Math.min(420, 140 + points.length * 5), easing: 'ease-out' }).finished } catch { /* Cleanup below. */ }
  }
  ghost.value = null
}
function cleanupDrag() {
  window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', end); window.removeEventListener('pointercancel', cancelDrag)
  active = null; path = []; overTarget.value = false
}
async function end(event: PointerEvent) {
  const item = active
  if (item && contains({ x: event.clientX, y: event.clientY })) { add(item); ghost.value = null }
  else { error.value = 'Drop the document inside the association area.'; await snapBack() }
  cleanupDrag()
}
function cancelDrag() { void snapBack().finally(cleanupDrag) }
function start(event: PointerEvent, item: DocumentItem) {
  if (event.button !== 0 || associated(item) || item.status !== 'indexed') return
  event.preventDefault(); active = item
  const point = { x: event.clientX, y: event.clientY }
  path = [point]; ghost.value = { label: item.filename, ...point }; error.value = null
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', end, { once: true }); window.addEventListener('pointercancel', cancelDrag, { once: true })
  void nextTick(() => ghostElement.value?.focus())
}

watch(() => props.workspaceId, () => { emit('update:modelValue', []); void load() }, { immediate: true })
watch(() => props.uploading, value => { if (!value) void load() })
onBeforeUnmount(() => { cancelLayoutAnimation(); cleanupDrag() })
</script>

<template>
  <div class="relative flex min-w-0 justify-center">
    <button ref="pill" type="button" class="flex h-8 min-w-0 max-w-56 items-center gap-1.5 rounded-full border border-white/10 bg-white/[.045] px-3 text-[11px] text-white/65 transition-colors hover:bg-white/[.08] hover:text-white/90"
      :class="viewState !== 'collapsed' ? 'invisible' : ''" :aria-expanded="viewState !== 'collapsed'" @click="toggle">
      <Loader2 v-if="uploading || taskActive" class="size-3.5 shrink-0 animate-spin text-sky-300" />
      <Check v-else-if="taskComplete" class="size-3.5 shrink-0 text-emerald-300" />
      <FileText v-else class="size-3.5 shrink-0" />
      <span class="truncate">Task documents · {{ modelValue.length }}</span><span class="hidden text-white/35 sm:inline">{{ statusLabel }}</span><ChevronUp class="size-3 shrink-0" />
    </button>
    <section v-if="viewState !== 'collapsed'" ref="card" class="absolute bottom-full left-1/2 z-30 mb-3 flex max-h-[min(62vh,34rem)] w-[min(36rem,calc(100vw-1.5rem))] -translate-x-1/2 flex-col overflow-hidden rounded-[18px] border border-white/12 bg-[#15181e]/98 text-left text-xs text-white/65 shadow-[0_24px_70px_rgba(0,0,0,.52)] backdrop-blur-xl">
      <header class="flex shrink-0 items-center justify-between gap-3 border-b border-white/[.08] px-4 py-3">
        <div class="min-w-0"><div class="truncate text-sm font-medium text-white/90">Task documents</div><div class="mt-0.5 truncate text-[11px] text-white/38">{{ agentRun?.goal || statusLabel }}</div></div>
        <button type="button" class="flex size-8 shrink-0 items-center justify-center rounded-lg hover:bg-white/[.07]" aria-label="Collapse task documents" @click="toggle"><ChevronDown class="size-4" /></button>
      </header>
      <div ref="details" class="min-h-0 overflow-y-auto p-4" :class="viewState === 'expanding' ? 'task-details-enter' : ''">
        <div ref="target" class="min-h-14 rounded-xl border border-dashed p-2.5 transition-colors" :class="overTarget ? 'border-sky-300/70 bg-sky-400/10' : 'border-white/10'">
          <div v-if="!modelValue.length" class="py-2 text-center text-white/30">Drop indexed documents here</div>
          <div v-else class="space-y-1.5">
            <div v-for="item in associatedDocuments" :key="item.document_id ?? item.filename" class="flex items-center gap-2 rounded-lg bg-white/[.045] px-2.5 py-2">
              <FileText class="size-3.5 shrink-0" /><span class="min-w-0 flex-1 truncate text-white/75">{{ item.filename }}</span><span class="text-[10px] capitalize text-emerald-300/65">{{ item.status }}</span>
              <button type="button" :aria-label="`Remove ${item.filename}`" class="rounded p-1 hover:bg-white/10" @click="item.document_id && remove(item.document_id)"><X class="size-3" /></button>
            </div>
          </div>
        </div>
        <div v-if="documents.some(item => !associated(item))" class="mt-3 space-y-1.5">
          <div class="text-[10px] uppercase tracking-[.12em] text-white/30">Available in Workspace</div>
          <div v-for="item in documents.filter(item => !associated(item))" :key="item.document_id ?? item.filename" class="flex items-center gap-2 rounded-lg border border-white/[.07] px-2.5 py-2">
            <button type="button" class="cursor-grab touch-none text-white/25 disabled:cursor-not-allowed" :disabled="item.status !== 'indexed'" :aria-label="`Drag ${item.filename}`" @pointerdown="start($event, item)"><GripVertical class="size-3.5" /></button>
            <span class="min-w-0 flex-1 truncate">{{ item.filename }}</span><span class="text-[10px] capitalize text-white/35">{{ item.status }}</span>
            <button type="button" class="rounded p-1 hover:bg-white/10 disabled:opacity-30" :disabled="item.status !== 'indexed'" :aria-label="`Associate ${item.filename}`" @click="add(item)"><Plus class="size-3.5" /></button>
          </div>
        </div>
        <div class="mt-4 flex flex-wrap items-center gap-2 border-t border-white/[.07] pt-3">
          <button type="button" class="rounded-lg bg-white/[.07] px-3 py-1.5 hover:bg-white/[.11]" @click="emit('request-upload')">Add documents</button>
          <RouterLink to="/files" class="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 hover:bg-white/[.07]"><FolderOpen class="size-3.5" />Open knowledge base</RouterLink>
          <span class="ml-auto text-[10px] text-white/30">{{ statusLabel }}</span>
        </div>
        <p v-if="error" class="mt-2 text-amber-200/75">{{ error }}</p>
      </div>
    </section>
  </div>
  <Teleport to="body"><div v-if="ghost" ref="ghostElement" tabindex="-1" class="pointer-events-none fixed z-[100] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-sky-300/40 bg-[#171c24] px-3 py-2 text-xs text-white shadow-2xl" :style="{ left: `${ghost.x}px`, top: `${ghost.y}px` }">{{ ghost.label }}</div></Teleport>
</template>

<style scoped>
.task-details-enter { animation: task-details-in 140ms 110ms ease-out both; }
@keyframes task-details-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
@media (prefers-reduced-motion: reduce) { .task-details-enter { animation: none; } }
</style>
