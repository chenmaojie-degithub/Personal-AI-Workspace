<script setup lang="ts">
import { ref, watch } from 'vue'
import { FileText, Paperclip, Trash2 } from 'lucide-vue-next'
import { useChat } from '@/lib/chat'
import { useWorkspaces } from '@/lib/workspaces'

type KnowledgeFile = { filename: string; session_id: string | null; bytes: number; status: string; chunk_count: number; ingest_error: string | null }
const chat = useChat()
const workspaces = useWorkspaces()
const files = ref<KnowledgeFile[]>([])
const loading = ref(false)
const uploading = ref(false)
const error = ref<string | null>(null)
const input = ref<HTMLInputElement | null>(null)
function apiBase() { return import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000' }

async function load() {
  try { await workspaces.ensureLoaded() } catch { error.value = workspaces.error.value; return }
  const id = workspaces.currentId.value
  if (!id) return
  loading.value = true
  error.value = null
  try {
    const response = await fetch(`${apiBase()}/files?workspace_id=${encodeURIComponent(id)}`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data = await response.json() as { files: KnowledgeFile[] }
    if (workspaces.currentId.value === id) files.value = data.files
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function upload(event: Event) {
  const element = event.target as HTMLInputElement
  const selected = Array.from(element.files ?? [])
  element.value = ''
  const id = workspaces.currentId.value
  if (!selected.length || !id) return
  uploading.value = true
  error.value = null
  try {
    const form = new FormData()
    selected.forEach(file => form.append('files', file))
    form.append('workspace_id', id)
    form.append('session_id', chat.sessionId.value)
    const response = await fetch(`${apiBase()}/files/upload`, { method: 'POST', body: form })
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`)
    const result = await response.json() as { ingest_error: string | null }
    if (result.ingest_error) error.value = result.ingest_error
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '上传失败'
  } finally {
    uploading.value = false
  }
}

async function remove(file: KnowledgeFile) {
  if (!window.confirm(`删除 ${file.filename} 及对应索引？`)) return
  const params = file.session_id
    ? `session_id=${encodeURIComponent(file.session_id)}`
    : `workspace_id=${encodeURIComponent(workspaces.currentId.value ?? '')}`
  try {
    const response = await fetch(`${apiBase()}/files/${encodeURIComponent(file.filename)}?${params}`, { method: 'DELETE' })
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`)
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '删除失败'
  }
}

watch(workspaces.currentId, () => { files.value = []; void load() }, { immediate: true })
</script>

<template>
  <div class="h-full overflow-y-auto bg-[#0b0d10] px-4 py-8 text-white sm:px-8">
    <div class="mx-auto max-w-[850px]">
      <div class="flex items-center justify-between gap-4">
        <div><p class="text-[11px] uppercase tracking-[.18em] text-white/35">Workspace Knowledge</p>
          <h1 class="mt-2 text-2xl font-medium">Knowledge Base</h1>
          <p class="mt-1 text-sm text-white/45">{{ workspaces.current.value?.name }}</p></div>
        <button type="button" class="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[.05] px-3 py-2 text-sm text-white/80 hover:bg-white/[.09]" :disabled="uploading" @click="input?.click()"><Paperclip class="size-4" />{{ uploading ? 'Uploading...' : 'Add files' }}</button>
        <input ref="input" type="file" multiple class="hidden" @change="upload" />
      </div>
      <p v-if="error" class="mt-6 rounded-xl border border-amber-300/20 bg-amber-300/[.04] p-3 text-sm text-amber-200">{{ error }}</p>
      <div v-if="loading" class="mt-10 space-y-3"><div v-for="n in 3" :key="n" class="h-12 animate-pulse rounded-xl bg-white/[.04]" /></div>
      <div v-else-if="!files.length" class="mt-20 text-center text-sm text-white/40">No files yet. Add documents to make them available in every chat in this Workspace.</div>
      <div v-else class="mt-8 divide-y divide-white/[.07]">
        <div v-for="file in files" :key="`${file.session_id ?? 'workspace'}:${file.filename}`" class="flex items-center gap-3 py-4">
          <FileText class="size-4 shrink-0 text-white/40" />
          <div class="min-w-0 flex-1"><div class="truncate text-sm text-white/85">{{ file.filename }}</div><div class="mt-1 text-xs text-white/40">{{ file.chunk_count }} chunks · {{ file.status === 'indexed' ? 'Indexed' : file.status === 'failed' ? 'Failed' : 'Not indexed' }}<span v-if="file.session_id"> · Legacy session file</span></div></div>
          <button type="button" class="rounded-lg p-2 text-white/35 hover:bg-white/[.07] hover:text-red-300" :aria-label="`Delete ${file.filename}`" @click="remove(file)"><Trash2 class="size-4" /></button>
        </div>
      </div>
    </div>
  </div>
</template>
