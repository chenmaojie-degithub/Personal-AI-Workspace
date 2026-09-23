<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import ModelSelector from '@/components/chat/ModelSelector.vue'
import { useChat } from '@/lib/chat'
import { useWorkspaces } from '@/lib/workspaces'

defineProps<{ compact?: boolean }>()
const chat = useChat()
const workspaces = useWorkspaces()
const name = ref('')
const description = ref('')
const systemPrompt = ref('')
const modelId = ref<string | null>(null)
const thinkMode = ref(false)
const webSearch = ref(false)
const dataAnalysis = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const saved = ref(false)
const confirmDelete = ref(false)
const dirty = computed(() => {
  const current = workspaces.current.value
  return !!current && (
    name.value.trim() !== current.name
    || description.value.trim() !== current.description
    || systemPrompt.value.trim() !== current.system_prompt
    || modelId.value !== current.default_model_id
    || thinkMode.value !== current.tool_settings.think_mode
    || webSearch.value !== current.tool_settings.web_search
    || dataAnalysis.value !== current.tool_settings.data_analysis
  )
})

watch(workspaces.current, (workspace) => {
  if (!workspace) return
  name.value = workspace.name
  description.value = workspace.description
  systemPrompt.value = workspace.system_prompt
  modelId.value = workspace.default_model_id
  thinkMode.value = workspace.tool_settings.think_mode
  webSearch.value = workspace.tool_settings.web_search
  dataAnalysis.value = workspace.tool_settings.data_analysis
  saved.value = false
  confirmDelete.value = false
}, { immediate: true })

watch([name, description, systemPrompt, modelId, thinkMode, webSearch, dataAnalysis], () => { saved.value = false })

async function save() {
  const current = workspaces.current.value
  if (!current || !name.value.trim()) return
  saving.value = true
  error.value = null
  try {
    await workspaces.update(current.id, {
      name: name.value.trim(), description: description.value.trim(),
      system_prompt: systemPrompt.value.trim(), default_model_id: modelId.value,
      tool_settings: { ...current.tool_settings, think_mode: thinkMode.value, web_search: webSearch.value, data_analysis: dataAnalysis.value },
    })
    if (chat.selectedModelId.value === current.default_model_id) chat.selectedModelId.value = modelId.value
    await nextTick()
    saved.value = true
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function remove() {
  const current = workspaces.current.value
  if (!current || current.is_default || chat.isLoading.value || chat.isRestoring.value) return
  saving.value = true
  error.value = null
  try {
    await workspaces.remove(current.id)
    if (workspaces.currentId.value) await chat.switchWorkspace(workspaces.currentId.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '删除失败'
  } finally {
    saving.value = false
    confirmDelete.value = false
  }
}
</script>

<template>
  <div class="workspace-settings max-h-[min(78vh,680px)] overflow-y-auto rounded-xl border border-white/10 bg-[#171a20] p-5 text-white shadow-2xl" :class="compact ? 'w-full' : 'mx-auto w-full max-w-2xl'">
    <h2 class="text-lg font-medium">Workspace Settings</h2>
    <p class="mt-1 text-xs text-white/40">{{ workspaces.current.value?.name }}</p>
    <div class="mt-5 space-y-5">
      <section class="space-y-3">
        <h3 class="text-[11px] uppercase tracking-[.16em] text-white/40">General</h3>
        <label class="block text-xs text-white/60">Name<input v-model="name" maxlength="100" class="mt-1.5 w-full rounded-lg border border-white/10 bg-white/[.04] px-3 py-2 text-sm text-white outline-none focus:border-white/25" /></label>
        <label class="block text-xs text-white/60">Description<input v-model="description" maxlength="1000" class="mt-1.5 w-full rounded-lg border border-white/10 bg-white/[.04] px-3 py-2 text-sm text-white outline-none focus:border-white/25" /></label>
      </section>
      <section class="space-y-3 border-t border-white/10 pt-4">
        <h3 class="text-[11px] uppercase tracking-[.16em] text-white/40">AI</h3>
        <div class="text-xs text-white/60">Default Model<div class="mt-1.5"><ModelSelector v-model="modelId" :models="chat.availableModels.value" /></div></div>
        <label class="block text-xs text-white/60">System Prompt<textarea v-model="systemPrompt" rows="4" maxlength="12000" class="mt-1.5 w-full resize-y rounded-lg border border-white/10 bg-white/[.04] px-3 py-2 text-sm text-white outline-none focus:border-white/25" /></label>
      </section>
      <section class="space-y-3 border-t border-white/10 pt-4">
        <h3 class="text-[11px] uppercase tracking-[.16em] text-white/40">Capabilities</h3>
        <label class="flex items-center justify-between text-sm text-white/75"><span>Think <span class="block text-xs text-white/35">Changes the assistant's response instructions.</span></span><input v-model="thinkMode" type="checkbox" class="size-4 accent-white" /></label>
        <label class="flex items-center justify-between text-sm text-white/75"><span>Web Search <span class="block text-xs text-white/35">Search current information with DDGS.</span></span><input v-model="webSearch" type="checkbox" class="size-4 accent-white" /></label>
        <label class="flex items-center justify-between text-sm text-white/75"><span>Data Analysis <span class="block text-xs text-white/35">Analyze Workspace CSV and XLSX files.</span></span><input v-model="dataAnalysis" type="checkbox" class="size-4 accent-white" /></label>
        <div class="flex items-center justify-between text-sm text-white/35"><span>Image Generation</span><span class="text-[11px]">Coming soon</span></div>
      </section>
      <p v-if="error" class="text-xs text-red-300">{{ error }}</p>
      <p v-else-if="dirty" class="text-xs text-amber-200/75">Unsaved changes</p>
      <p v-else-if="saved" class="text-xs text-emerald-200/75">Settings saved</p>
      <button type="button" :disabled="saving || !name.trim()" class="w-full rounded-lg bg-white px-4 py-2 text-sm font-medium text-[#15171c] disabled:opacity-40" @click="save">Save settings</button>
      <section class="border-t border-white/10 pt-4">
        <h3 class="text-[11px] uppercase tracking-[.16em] text-red-300/70">Danger Zone</h3>
        <p v-if="workspaces.current.value?.is_default" class="mt-2 text-xs text-white/35">Default Workspace cannot be deleted.</p>
        <template v-else>
          <button v-if="!confirmDelete" type="button" class="mt-2 text-xs text-red-300/80 hover:text-red-200" @click="confirmDelete = true">Delete Workspace...</button>
          <div v-else class="mt-2 space-y-2 rounded-lg border border-red-400/20 bg-red-400/5 p-3">
            <p class="text-xs text-red-200">Delete this Workspace, its chats, usage and knowledge files? This cannot be undone.</p>
            <div class="flex gap-3 text-xs"><button type="button" class="text-red-300 disabled:opacity-40" :disabled="saving || chat.isLoading.value || chat.isRestoring.value" @click="remove">Confirm delete</button><button type="button" class="text-white/60" @click="confirmDelete = false">Cancel</button></div>
          </div>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.workspace-settings { scrollbar-color: #ffffff25 transparent; scrollbar-width: thin; }
</style>
