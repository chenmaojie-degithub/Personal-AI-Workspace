<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ChevronDown, Check, Plus, Sparkles } from 'lucide-vue-next'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import ModelSelector from '@/components/chat/ModelSelector.vue'
import { useChat } from '@/lib/chat'
import { useWorkspaces } from '@/lib/workspaces'

const chat = useChat()
const workspaces = useWorkspaces()
const open = ref(false)
const creating = ref(false)
const busy = ref(false)
const formError = ref<string | null>(null)
const name = ref('')
const description = ref('')
const systemPrompt = ref('')
const defaultModel = ref<string | null>(null)

onMounted(() => { void workspaces.ensureLoaded().catch(() => {}) })

async function choose(id: string) {
  if (chat.isLoading.value) return
  await chat.switchWorkspace(id)
  open.value = false
}

async function create() {
  if (!name.value.trim() || busy.value || chat.isLoading.value || chat.isRestoring.value) return
  busy.value = true
  formError.value = null
  try {
    const workspace = await workspaces.create({
      name: name.value.trim(), description: description.value.trim(),
      system_prompt: systemPrompt.value.trim(), default_model_id: defaultModel.value,
    })
    await chat.switchWorkspace(workspace.id)
    creating.value = false
    name.value = description.value = systemPrompt.value = ''
    defaultModel.value = null
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '创建失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <button type="button" class="flex w-full min-w-0 items-center gap-2 rounded-xl px-2 py-2 text-left transition-colors hover:bg-white/[0.06]"
        aria-label="选择工作区" :disabled="chat.isLoading.value">
        <Sparkles class="size-[18px] shrink-0 text-white/80" />
        <span class="min-w-0 flex-1 group-data-[collapsible=icon]:hidden">
          <span class="block truncate text-sm font-medium text-white/90">{{ workspaces.current.value?.name ?? 'Workspace' }}</span>
          <span class="block text-[10px] tracking-wide text-white/40">WORKSPACE</span>
        </span>
        <ChevronDown class="size-4 shrink-0 text-white/40 transition-transform duration-200 group-data-[collapsible=icon]:hidden" :class="open && 'rotate-180'" />
      </button>
    </PopoverTrigger>
    <PopoverContent side="bottom" align="start" class="workspace-menu z-50 w-60 rounded-xl p-1.5">
      <div class="px-2 pb-1 pt-1 text-[10px] font-medium uppercase tracking-[0.16em] text-white/40">Workspaces</div>
      <button v-for="item in workspaces.items.value" :key="item.id" type="button"
        class="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-white/65 transition-colors hover:bg-white/[0.07] hover:text-white"
        @click="choose(item.id)">
        <span class="truncate">{{ item.name }}</span><Check v-if="item.id === workspaces.currentId.value" class="size-4 shrink-0 text-white/70" />
      </button>
      <div class="my-1 h-px bg-white/10" />
      <button type="button" class="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-white/70 hover:bg-white/[0.07]" @click="open = false; creating = true">
        <Plus class="size-4" /> 新建工作区
      </button>
    </PopoverContent>
  </Popover>

  <Dialog v-model:open="creating">
    <DialogContent class="border-white/10 bg-[#171a20] text-white shadow-2xl sm:max-w-md">
      <DialogHeader><DialogTitle>新建工作区</DialogTitle></DialogHeader>
      <form class="space-y-4" @submit.prevent="create">
        <label class="block text-xs text-white/55">名称 *<input v-model="name" required maxlength="100" class="mt-1.5 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white outline-none focus:border-white/25" /></label>
        <label class="block text-xs text-white/55">描述<input v-model="description" maxlength="1000" class="mt-1.5 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white outline-none focus:border-white/25" /></label>
        <div class="text-xs text-white/55">默认模型<div class="mt-1.5"><ModelSelector v-model="defaultModel" :models="chat.availableModels.value" /></div></div>
        <label class="block text-xs text-white/55">System Prompt<textarea v-model="systemPrompt" rows="3" maxlength="12000" class="mt-1.5 w-full resize-y rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white outline-none focus:border-white/25" /></label>
        <p v-if="formError" class="text-xs text-red-300">{{ formError }}</p>
        <button type="submit" :disabled="busy || chat.isLoading.value || chat.isRestoring.value || !name.trim()" class="w-full rounded-lg bg-white px-4 py-2.5 text-sm font-medium text-[#15171c] disabled:opacity-40">创建并切换</button>
      </form>
    </DialogContent>
  </Dialog>
</template>

<style>
.workspace-menu { border: 1px solid rgba(255,255,255,.09); background: rgba(16,18,22,.94); box-shadow: 0 12px 40px rgba(0,0,0,.36); backdrop-filter: blur(18px); color: #e8eaf0; }
.workspace-menu[data-state="open"] { animation: workspace-open 200ms cubic-bezier(.22,.8,.25,1) both; }
.workspace-menu[data-state="closed"] { animation: workspace-close 160ms ease both; }
@keyframes workspace-open { from { opacity: 0; transform: translateY(-6px) scale(.98); filter: blur(4px); } to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); } }
@keyframes workspace-close { from { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); } to { opacity: 0; transform: translateY(-6px) scale(.98); filter: blur(4px); } }
@media (prefers-reduced-motion: reduce) { .workspace-menu[data-state] { animation: none; } }
</style>
