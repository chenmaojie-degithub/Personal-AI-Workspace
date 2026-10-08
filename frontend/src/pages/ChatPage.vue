<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Pencil, Plus, Settings } from 'lucide-vue-next'
import MessageList from '@/components/chat/MessageList.vue'
import MessageComposer from '@/components/chat/MessageComposer.vue'
import AttachmentChips from '@/components/chat/AttachmentChips.vue'
import ModelSelector from '@/components/chat/ModelSelector.vue'
import CapabilitiesCard from '@/components/settings/CapabilitiesCard.vue'
import DocumentDropZone from '@/components/files/DocumentDropZone.vue'
import { useChat } from '@/lib/chat'
import type { UiAttachment } from '@/lib/chat'
import { useWorkspaces } from '@/lib/workspaces'

const chat = useChat()
const workspaces = useWorkspaces()
onMounted(() => { void chat.loadModels(); if (!chat.isRestoring.value) void chat.loadHistory() })
const controlsOpen = ref(false)

const hasMessages = computed(() => (chat.messages.value ?? []).some((m) => m.role === 'user'))
const chatTitle = computed(() => chat.sessions.value.find((item) => item.session_id === chat.sessionId.value)?.title
  ?? chat.messages.value.find((m) => m.role === 'user')?.content.replace(/\s+/g, ' ').trim()
  ?? 'New Chat')
const canRenameTitle = computed(() => chat.sessions.value.some((item) => item.session_id === chat.sessionId.value))
const editingTitle = ref(false)
const titleDraft = ref('')
const titleInput = ref<HTMLInputElement | null>(null)

function startTitleEdit() {
  if (!canRenameTitle.value) return
  titleDraft.value = chatTitle.value
  editingTitle.value = true
  void nextTick(() => { titleInput.value?.focus(); titleInput.value?.select() })
}

function cancelTitleEdit() { editingTitle.value = false }

async function saveTitleEdit() {
  if (!editingTitle.value) return
  editingTitle.value = false
  const title = titleDraft.value.trim()
  if (!title || title.length > 100) {
    chat.sessionsError.value = '标题需要包含 1–100 个字符'
    return
  }
  await chat.renameSession(chat.sessionId.value, title)
}

watch(() => chat.sessionId.value, () => { editingTitle.value = false })
const composerRef = ref<InstanceType<typeof MessageComposer> | null>(null)
const suggestions = [
  { label: '学习一个概念', prompt: '请用简单例子解释：' },
  { label: '分析代码', prompt: '请帮我分析这段代码：' },
  { label: '整理资料', prompt: '请帮我整理以下资料：' },
  { label: '询问知识库', prompt: '请根据我上传的资料回答：' },
]

const isUploading = chat.isUploading
const fileInputRef = ref<HTMLInputElement | null>(null)
const scrollAreaRef = ref<HTMLElement | null>(null)
const autoScrollArmed = ref(false)
const uploadStatus = ref<{ kind: 'success' | 'warning' | 'error'; text: string } | null>(null)
let uploadStatusTimer: number | null = null
const composerAttachments = ref<UiAttachment[]>([])

function setUploadStatus(next: { kind: 'success' | 'warning' | 'error'; text: string } | null) {
  uploadStatus.value = next
  if (uploadStatusTimer) window.clearTimeout(uploadStatusTimer)
  uploadStatusTimer = null
  if (next) {
    uploadStatusTimer = window.setTimeout(() => {
      uploadStatus.value = null
      uploadStatusTimer = null
    }, 6000)
  }
}

function scrollToLastMessage(behavior: ScrollBehavior = 'smooth') {
  const root = scrollAreaRef.value
  if (!root) return
  root.scrollTo({ top: root.scrollHeight, behavior })
}

function onMessagesScroll() {
  const root = scrollAreaRef.value
  if (root) autoScrollArmed.value = root.scrollHeight - root.scrollTop - root.clientHeight < 120
}

function onSend(text: string) {
  autoScrollArmed.value = true
  // Snapshot current attachments onto this outgoing user message.
  const attachments = composerAttachments.value.length ? composerAttachments.value.map((a) => ({ ...a })) : undefined
  composerAttachments.value = []
  void chat.send(text, { attachments })
  void nextTick(() => scrollToLastMessage('auto'))
}

watch(() => chat.sessionId.value, () => {
  composerRef.value?.setText('')
  composerAttachments.value = []
  setUploadStatus(null)
  autoScrollArmed.value = true
})

watch(
  () => (chat.messages.value ?? []).length,
  () => {
    if (!autoScrollArmed.value) return
    void nextTick(() => scrollToLastMessage('auto'))
  },
)

watch(
  () => chat.messages.value[chat.messages.value.length - 1]?.content.length,
  () => {
    if (autoScrollArmed.value) void nextTick(() => scrollToLastMessage('auto'))
  },
)

watch(
  () => chat.isLoading.value,
  (loading) => {
    if (!autoScrollArmed.value) return
    void nextTick(() => scrollToLastMessage(loading ? 'auto' : 'smooth'))
  },
)

function triggerFilePicker() {
  fileInputRef.value?.click()
}

function onFilePick(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  if (!files.length) return
  void onUpload(files)
  // Allow picking the same file again later.
  input.value = ''
}

function makeAttachmentId() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = (globalThis as any).crypto as Crypto | undefined
  return c?.randomUUID ? c.randomUUID() : `att_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function removeAttachment(id: string) {
  composerAttachments.value = composerAttachments.value.filter((a) => a.id !== id)
}

async function onUpload(files: File[]) {
  if (!files.length || isUploading.value) return

  isUploading.value = true
  setUploadStatus(null)
  try {
    // Create UI attachments immediately (uploading state) and keep them visible in the composer.
    const newAttachments: UiAttachment[] = files.map((f) => ({
      id: makeAttachmentId(),
      filename: f.name,
      bytes: f.size,
      contentType: f.type,
      status: 'uploading',
      detail: null,
    }))
    composerAttachments.value = [...composerAttachments.value, ...newAttachments]

    const formData = new FormData()
    files.forEach((f) => formData.append('files', f))
    if (chat.sessionId.value) {
      formData.append('session_id', chat.sessionId.value)
    }
    if (workspaces.currentId.value) formData.append('workspace_id', workspaces.currentId.value)

    const apiBase = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
    const res = await fetch(`${apiBase}/files/upload`, {
      method: 'POST',
      body: formData,
    })

    if (!res.ok) {
      const text = await res.text()
      throw new Error(`Upload failed: ${text}`)
    }

    const data = await res.json()
    if (data.session_id && !chat.sessionId.value) {
      chat.sessionId.value = data.session_id
    }

    const ingestError: string | null = typeof data.ingest_error === 'string' ? data.ingest_error : null

    // Mark these attachments as uploaded (or warning if ingest failed).
    const byName = new Map<string, { bytes?: number; contentType?: string }>()
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    for (const s of (data.stored ?? []) as any[]) {
      if (s?.filename) byName.set(String(s.filename), { bytes: s?.bytes, contentType: s?.content_type })
    }

    composerAttachments.value = composerAttachments.value.map((a) => {
      const isNew = newAttachments.some((n) => n.id === a.id)
      if (!isNew) return a
      const meta = byName.get(a.filename)
      return {
        ...a,
        bytes: meta?.bytes ?? a.bytes,
        contentType: meta?.contentType ?? a.contentType,
        status: ingestError ? 'warning' : 'uploaded',
        detail: ingestError ? `Ingest failed: ${ingestError}` : null,
      }
    })

    const uploadedNames = (data.stored ?? [])
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .map((s: any) => s?.filename)
      .filter((x: unknown): x is string => typeof x === 'string' && x.length > 0)
      .join(', ')

    if (data.ingest_error) {
      setUploadStatus({
        kind: 'warning',
        text: `Uploaded${uploadedNames ? `: ${uploadedNames}` : ''}. Ingest failed: ${data.ingest_error}`,
      })
    } else {
      setUploadStatus({
        kind: 'success',
        text: `Uploaded${uploadedNames ? `: ${uploadedNames}` : ''}.`,
      })
    }

  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Upload failed'
    setUploadStatus({ kind: 'error', text: `Upload failed: ${msg}` })
    // Mark any currently-uploading attachments as error (best effort).
    composerAttachments.value = composerAttachments.value.map((a) =>
      a.status === 'uploading' ? { ...a, status: 'error', detail: msg } : a,
    )
  } finally {
    isUploading.value = false
  }
}

// removeFile removed (handled by removeAttachment)
</script>

<template>
  <DocumentDropZone class="h-full min-h-0" :disabled="isUploading" @files="onUpload" @invalid="(text: string) => setUploadStatus({ kind: 'error', text })">
  <div data-chat-page class="flex h-full min-h-0 flex-col bg-[#0b0d10]">
    <div ref="scrollAreaRef" data-messages-viewport class="min-h-0 flex-1 overflow-y-auto px-4 pt-5 sm:px-6 sm:pt-7" @scroll="onMessagesScroll">
      <div v-if="!hasMessages" class="flex min-h-full items-center justify-center pb-12">
        <div class="w-full max-w-[850px] text-center">
          <div class="mb-3 text-[11px] font-semibold tracking-[0.22em] text-white/35">PERSONAL AI WORKSPACE</div>
          <h2 class="text-3xl font-medium tracking-tight text-white/90 sm:text-4xl">What are you working on?</h2>
          <p class="mt-3 text-sm text-white/40">A place to think, build, and explore your knowledge.</p>
          <div class="mx-auto mt-8 flex max-w-xl flex-wrap justify-center gap-2">
            <button v-for="item in suggestions" :key="item.label" type="button"
              class="rounded-full border border-white/[0.08] bg-white/[0.025] px-4 py-2 text-xs text-white/60 transition-colors hover:border-white/[0.16] hover:bg-white/[0.06] hover:text-white"
              @click="composerRef?.setText(item.prompt)">{{ item.label }}</button>
          </div>
        </div>
      </div>
      <div v-else class="mx-auto w-full max-w-[850px] pb-10">
        <div class="group mb-7 flex min-w-0 items-center gap-1 text-white/40">
          <input v-if="editingTitle" ref="titleInput" v-model="titleDraft" type="text" maxlength="100" aria-label="编辑当前聊天标题"
            class="min-w-0 w-full rounded-md border border-white/15 bg-[#20242b] px-2 py-1.5 text-sm text-white outline-none focus:border-white/30"
            @keydown.enter.prevent="saveTitleEdit" @keydown.esc.prevent="cancelTitleEdit" @blur="saveTitleEdit" />
          <template v-else>
            <h1 class="min-w-0 truncate text-sm" :title="chatTitle" @dblclick="startTitleEdit">{{ chatTitle }}</h1>
            <button v-if="canRenameTitle" type="button" class="shrink-0 rounded p-1 opacity-0 transition-opacity hover:text-white/75 group-hover:opacity-100 focus-visible:opacity-100"
              aria-label="重命名当前聊天" title="重命名当前聊天" @click="startTitleEdit"><Pencil class="size-3" /></button>
          </template>
        </div>
        <MessageList :messages="chat.messages.value ?? []" :is-loading="chat.isLoading.value" />
        <div v-if="chat.lastError.value" class="mt-6 rounded-xl border border-red-400/20 bg-red-400/5 p-3 text-sm text-red-300">{{ chat.lastError.value }}</div>
      </div>
    </div>

    <div data-composer-dock class="z-10 shrink-0 bg-gradient-to-t from-[#0b0d10] via-[#0b0d10] to-transparent px-3 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-7 sm:px-6 sm:pb-6 sm:pt-9">
      <div class="mx-auto w-full max-w-[880px]">
        <input ref="fileInputRef" type="file" multiple accept=".txt,.md,.markdown,.pdf,.docx,.csv,.xlsx" class="hidden" @change="onFilePick" />
        <MessageComposer ref="composerRef" :disabled="!chat.canSend.value" :streaming="chat.isLoading.value" @send="onSend" @stop="chat.stop">
          <template #attachments>
            <AttachmentChips v-if="composerAttachments.length" class="px-4 pt-3" :attachments="composerAttachments" removable @remove="removeAttachment" />
          </template>
          <template #prepend>
            <button type="button" class="flex size-9 items-center justify-center rounded-xl text-white/50 transition-colors hover:bg-white/[0.08] hover:text-white"
              title="添加文件" aria-label="添加文件" :disabled="isUploading" @click="triggerFilePicker">
              <Plus class="size-[18px]" />
            </button>
            <div class="composer-model min-w-0"><ModelSelector v-model="chat.selectedModelId.value" :models="chat.availableModels.value" :disabled="chat.isLoading.value" /></div>
          </template>
          <template #actions>
            <span v-if="isUploading" class="hidden sm:inline">Uploading...</span>
          </template>
          <template #before-send>
            <Popover :open="controlsOpen" @update:open="(v: boolean) => (controlsOpen = v)">
              <PopoverTrigger as-child>
                <button type="button" class="flex size-9 items-center justify-center rounded-xl text-white/50 transition-colors hover:bg-white/[0.07] hover:text-white" aria-label="设置" title="设置">
                  <Settings class="size-4" />
                </button>
              </PopoverTrigger>
              <PopoverContent side="top" align="end" class="z-50 w-[calc(100vw-2rem)] border-white/10 bg-[#171a20] p-0 text-white sm:w-95">
                <CapabilitiesCard compact />
              </PopoverContent>
            </Popover>
          </template>
        </MessageComposer>
        <p v-if="uploadStatus" class="mt-2 truncate px-2 text-xs" :class="uploadStatus.kind === 'success' ? 'text-emerald-300/70' : uploadStatus.kind === 'warning' ? 'text-amber-300/80' : 'text-red-300'" :title="uploadStatus.text">{{ uploadStatus.text }}</p>
        <p v-if="chat.isRestoring.value" class="mt-2 px-2 text-xs text-white/40">Restoring chat history...</p>
        <p v-if="chat.lastError.value && !hasMessages" class="mt-2 px-2 text-xs text-red-300">{{ chat.lastError.value }}</p>
      </div>
    </div>
  </div>
  </DocumentDropZone>
</template>

<style scoped>
[data-messages-viewport] { scrollbar-color: rgba(255, 255, 255, .18) transparent; scrollbar-width: thin; }
[data-messages-viewport]::-webkit-scrollbar { width: 6px; }
[data-messages-viewport]::-webkit-scrollbar-thumb { border-radius: 999px; background: rgba(255, 255, 255, .18); }
.composer-model :deep(.model-trigger) {
  min-width: 0;
  max-width: min(40vw, 160px);
  border-color: transparent;
  background: transparent;
  box-shadow: none;
  padding-inline: 8px;
}
.composer-model :deep(.model-trigger:hover) { background: rgba(255, 255, 255, .06); }
</style>
