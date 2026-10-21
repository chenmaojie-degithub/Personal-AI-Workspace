<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMemories } from '@/lib/memories'
import type { Memory } from '@/lib/memories'
import { useWorkspaces } from '@/lib/workspaces'

const workspaces = useWorkspaces()
const memory = useMemories(workspaces.currentId)
const key = ref('')
const value = ref('')
const confirmed = ref(false)
const editing = ref<Memory | null>(null)
const deleting = ref<Memory | null>(null)
let formEpoch = 0
const busy = computed(() => memory.loading.value || memory.saving.value)
const blocked = computed(() => busy.value || memory.unavailable.value || !workspaces.currentId.value)
const latestEditing = computed(() => memory.rows.value.find(row => row.id === editing.value?.id))
const staleEdit = computed(() => !!editing.value && latestEditing.value?.version !== editing.value.version)
function clearForm() { key.value = value.value = ''; confirmed.value = false; editing.value = null }
watch(workspaces.currentId, () => { formEpoch++; clearForm(); deleting.value = null }, { flush: 'sync' })
function edit(row: Memory) { editing.value = { ...row }; key.value = row.key; value.value = row.value; confirmed.value = false; deleting.value = null }
async function submit() {
  if (staleEdit.value) return
  const generation = formEpoch
  const success = editing.value
    ? await memory.update(editing.value, value.value, confirmed.value)
    : await memory.create(key.value, value.value, confirmed.value)
  if (generation !== formEpoch) return
  // A conflict keeps the draft, but requires a fresh edit/version and confirmation.
  confirmed.value = false
  if (success) clearForm()
}
async function remove() {
  if (!deleting.value) return
  const generation = formEpoch
  const success = await memory.remove(deleting.value, true)
  if (generation === formEpoch) {
    deleting.value = null
    if (success) clearForm()
  }
}
function displayTime(value: string) { return new Date(value).toLocaleString() }
</script>

<template>
  <section aria-labelledby="memory-title" class="mx-auto mt-6 w-full max-w-2xl rounded-xl border border-white/10 bg-[#171a20] p-5 text-white shadow-2xl">
    <div class="flex items-start justify-between gap-4">
      <div><h2 id="memory-title" class="text-lg font-medium">Memory 管理</h2><p class="mt-1 text-xs text-white/40">{{ workspaces.current.value?.name }} · 仅手动确认的长期信息</p></div>
      <button type="button" class="text-xs text-white/65 disabled:opacity-40" :disabled="busy || !workspaces.currentId.value" @click="memory.reload">刷新记忆</button>
    </div>
    <p class="mt-3 text-xs leading-relaxed text-white/45">记忆属于当前 Workspace，可用于其他会话。不会自动提取，也不会通过此页面开启 Memory。</p>
    <p v-if="memory.error.value" role="alert" class="mt-3 text-sm text-amber-200">{{ memory.error.value }}</p>
    <p v-if="memory.loading.value" role="status" class="mt-3 text-sm text-white/50">正在加载记忆…</p>
    <p v-else-if="!memory.rows.value.length && !memory.unavailable.value" class="mt-3 text-sm text-white/50">当前 Workspace 暂无记忆。</p>
    <ul class="mt-4 space-y-3">
      <li v-for="row in memory.rows.value" :key="row.id" class="rounded-lg border border-white/10 bg-white/[.025] p-3">
        <div class="flex flex-wrap items-start justify-between gap-2"><h3 class="break-all text-sm font-medium">{{ row.key }}</h3><span class="text-xs text-white/40">v{{ row.version }}</span></div>
        <p class="mt-2 whitespace-pre-wrap break-words text-sm text-white/75">{{ row.value }}</p>
        <p class="mt-2 text-xs text-white/35">更新于 {{ displayTime(row.updated_at) }}</p>
        <div class="mt-3 flex gap-4 text-xs"><button type="button" :disabled="blocked" class="text-white/75 disabled:opacity-40" @click="edit(row)">修改 {{ row.key }}</button><button type="button" :disabled="blocked" class="text-red-300 disabled:opacity-40" @click="deleting = { ...row }">删除 {{ row.key }}</button></div>
      </li>
    </ul>
    <div v-if="deleting" role="alertdialog" aria-label="确认删除记忆" class="mt-4 rounded-lg border border-red-400/25 bg-red-400/5 p-3">
      <p class="text-sm text-red-200">永久删除记忆「{{ deleting.key }}」？后续检索不再使用它，已有回答、备份和运行快照不会被抹除。</p>
      <div class="mt-3 flex gap-4 text-xs"><button type="button" :disabled="blocked" class="text-red-300 disabled:opacity-40" @click="remove">确认删除记忆</button><button type="button" :disabled="memory.saving.value" class="text-white/65" @click="deleting = null">取消删除</button></div>
    </div>
    <form class="mt-5 space-y-3 border-t border-white/10 pt-4" @submit.prevent="submit">
      <h3 class="text-sm font-medium">{{ editing ? '修改记忆（保留 key）' : '新建记忆' }}</h3>
      <div v-if="staleEdit" class="space-y-2 text-xs text-amber-200"><p>编辑版本已过期，草稿已保留。请先核对最新记录。</p><button v-if="latestEditing" type="button" :disabled="blocked" class="underline disabled:opacity-40" @click="edit(latestEditing)">载入最新版本（会替换草稿）</button></div>
      <label class="block text-xs text-white/60">Memory key<input v-model="key" aria-label="Memory key" maxlength="80" required :disabled="blocked || !!editing" class="mt-1.5 w-full rounded-lg border border-white/10 bg-white/[.04] px-3 py-2 text-sm text-white disabled:opacity-40" /></label>
      <label class="block text-xs text-white/60">Memory value<textarea v-model="value" aria-label="Memory value" maxlength="1000" required rows="3" :disabled="blocked" class="mt-1.5 w-full resize-y rounded-lg border border-white/10 bg-white/[.04] px-3 py-2 text-sm text-white disabled:opacity-40" /></label>
      <label class="flex items-start gap-2 text-xs text-white/65"><input v-model="confirmed" type="checkbox" :disabled="blocked" class="mt-0.5 accent-white" /><span>我确认将以上信息保存为当前 Workspace 的长期记忆。请勿保存密码或 API Key。</span></label>
      <div class="flex items-center gap-4"><button type="submit" :disabled="blocked || staleEdit || !confirmed || !key.trim() || !value.trim()" class="rounded-lg bg-white px-4 py-2 text-sm font-medium text-[#15171c] disabled:opacity-40">{{ editing ? '确认修改记忆' : '确认创建记忆' }}</button><button v-if="editing" type="button" :disabled="memory.saving.value" class="text-xs text-white/60" @click="clearForm">取消修改</button></div>
    </form>
    <section class="mt-5 border-t border-white/10 pt-4">
      <h3 class="text-sm font-medium">生命周期检查</h3>
      <p class="mt-2 text-xs leading-relaxed text-white/45">删除 Workspace 不会自动清理独立记忆。预览只展示孤立记录数量；清理前需备份、重新核对归属并单独确认。恢复旧备份可能重新带回已删除记忆。</p>
      <button type="button" :disabled="memory.previewLoading.value || memory.unavailable.value || !workspaces.currentId.value" class="mt-3 text-xs text-white/75 disabled:opacity-40" @click="memory.inspectOrphans">预览孤立记忆</button>
      <div v-if="memory.preview.value" role="status" class="mt-3 space-y-2 text-xs text-white/65">
        <p>检测到 {{ memory.preview.value.record_count }} 条孤立记忆。仅预览，全部保留，未执行清理。</p>
        <p v-for="group in memory.preview.value.orphans" :key="group.workspace_id" class="break-all">Workspace {{ group.workspace_id }}：{{ group.count }} 条</p>
        <p>业务库与记忆库不是原子快照，请勿据此直接删除。</p>
      </div>
    </section>
  </section>
</template>
