<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { FileText, GripVertical, Plus, X } from 'lucide-vue-next'

type DocumentItem = { document_id: string | null; filename: string; status: string }
type Point = { x: number; y: number }

const props = defineProps<{ workspaceId: string | null; modelValue: string[] }>()
const emit = defineEmits<{ 'update:modelValue': [ids: string[]] }>()
const documents = ref<DocumentItem[]>([])
const error = ref<string | null>(null)
const target = ref<HTMLElement | null>(null)
const ghostElement = ref<HTMLElement | null>(null)
const ghost = ref<{ label: string; x: number; y: number } | null>(null)
const overTarget = ref(false)
let active: DocumentItem | null = null
let path: Point[] = []

function apiBase() { return import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000' }
async function load() {
  if (!props.workspaceId) { documents.value = []; return }
  try {
    const response = await fetch(`${apiBase()}/files?workspace_id=${encodeURIComponent(props.workspaceId)}`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data = await response.json() as { files: DocumentItem[] }
    documents.value = data.files.filter(item => item.document_id && item.status === 'indexed')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Could not load documents'
  }
}

function associated(item: DocumentItem) { return !!item.document_id && props.modelValue.includes(item.document_id) }
function add(item: DocumentItem) {
  if (item.document_id && !associated(item)) emit('update:modelValue', [...props.modelValue, item.document_id])
}
function remove(id: string) { emit('update:modelValue', props.modelValue.filter(item => item !== id)) }
function contains(point: Point) {
  const rect = target.value?.getBoundingClientRect()
  return !!rect && point.x >= rect.left && point.x <= rect.right && point.y >= rect.top && point.y <= rect.bottom
}

function move(event: PointerEvent) {
  if (!active || !ghost.value) return
  const point = { x: event.clientX, y: event.clientY }
  path.push(point)
  ghost.value = { ...ghost.value, ...point }
  overTarget.value = contains(point)
}

async function snapBack() {
  const element = ghostElement.value
  const points = [...path].reverse()
  if (element && points.length > 1 && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const stride = Math.max(1, Math.floor(points.length / 24))
    const sampled = points.filter((_, index) => index % stride === 0)
    const finalPoint = points[points.length - 1]!
    if (sampled[sampled.length - 1] !== finalPoint) sampled.push(finalPoint)
    try {
      await element.animate(
        sampled.map(point => ({ left: `${point.x}px`, top: `${point.y}px` })),
        { duration: Math.min(420, 140 + points.length * 5), easing: 'ease-out' },
      ).finished
    } catch { /* Cancellation still performs cleanup below. */ }
  }
  ghost.value = null
}

function cleanup() {
  window.removeEventListener('pointermove', move)
  window.removeEventListener('pointerup', end)
  window.removeEventListener('pointercancel', cancel)
  active = null
  path = []
  overTarget.value = false
}

async function end(event: PointerEvent) {
  const item = active
  const valid = !!item && contains({ x: event.clientX, y: event.clientY })
  if (valid) {
    add(item)
    ghost.value = null
  } else {
    error.value = 'Drop the document inside the association area.'
    await snapBack()
  }
  cleanup()
}

function cancel() { void snapBack().finally(cleanup) }

function start(event: PointerEvent, item: DocumentItem) {
  if (event.button !== 0 || associated(item)) return
  event.preventDefault()
  active = item
  const point = { x: event.clientX, y: event.clientY }
  path = [point]
  ghost.value = { label: item.filename, ...point }
  error.value = null
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', end, { once: true })
  window.addEventListener('pointercancel', cancel, { once: true })
  void nextTick(() => ghostElement.value?.focus())
}

watch(() => props.workspaceId, () => { emit('update:modelValue', []); void load() }, { immediate: true })
onBeforeUnmount(cleanup)
</script>

<template>
  <section v-if="documents.length || modelValue.length" class="mb-3 rounded-xl border border-white/[.08] bg-white/[.02] p-3 text-xs text-white/55">
    <div class="mb-2 flex items-center justify-between"><span>Task documents</span><span class="text-white/30">Drag into the box or use +</span></div>
    <div ref="target" class="min-h-12 rounded-lg border border-dashed p-2 transition-colors" :class="overTarget ? 'border-sky-300/70 bg-sky-400/10' : 'border-white/10'">
      <div v-if="!modelValue.length" class="py-1 text-center text-white/30">Drop documents here to associate them with the next Agent task</div>
      <div v-else class="flex flex-wrap gap-2">
        <span v-for="id in modelValue" :key="id" class="inline-flex max-w-full items-center gap-1 rounded-lg bg-white/[.06] px-2 py-1">
          <FileText class="size-3" /><span class="truncate">{{ documents.find(item => item.document_id === id)?.filename ?? id }}</span>
          <button type="button" aria-label="Remove document" class="rounded p-0.5 hover:bg-white/10" @click="remove(id)"><X class="size-3" /></button>
        </span>
      </div>
    </div>
    <div class="mt-2 flex gap-2 overflow-x-auto pb-1">
      <div v-for="item in documents.filter(item => !associated(item))" :key="item.document_id ?? item.filename" class="flex shrink-0 items-center gap-1 rounded-lg border border-white/[.08] px-2 py-1.5">
        <button type="button" class="cursor-grab touch-none text-white/30 active:cursor-grabbing" :aria-label="`Drag ${item.filename}`" @pointerdown="start($event, item)"><GripVertical class="size-3.5" /></button>
        <span class="max-w-36 truncate">{{ item.filename }}</span>
        <button type="button" class="rounded p-0.5 hover:bg-white/10" :aria-label="`Associate ${item.filename}`" @click="add(item)"><Plus class="size-3.5" /></button>
      </div>
    </div>
    <p v-if="error" class="mt-2 text-amber-200/75">{{ error }}</p>
  </section>
  <Teleport to="body">
    <div v-if="ghost" ref="ghostElement" tabindex="-1" class="pointer-events-none fixed z-[100] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-sky-300/40 bg-[#171c24] px-3 py-2 text-xs text-white shadow-2xl" :style="{ left: `${ghost.x}px`, top: `${ghost.y}px` }">
      {{ ghost.label }}
    </div>
  </Teleport>
</template>
