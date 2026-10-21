<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChevronDown, ChevronRight, Folder, FolderPlus, GripVertical, MessageSquare, MoreHorizontal, Plus } from 'lucide-vue-next'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useSidebar } from '@/components/ui/sidebar'
import DragPlaceholder from './DragPlaceholder.vue'
import { useChat } from '@/lib/chat'
import { useWorkspaces } from '@/lib/workspaces'
import { createProjectFolder, loadProjectTree, moveProjectItem, renameProjectFolder, type ProjectItemType, type ProjectTreeData } from '@/lib/projects'

type Row = { key: string; kind: ProjectItemType; id: string; parentId: string | null; title: string; depth: number; position: number }
type DropTarget = { parentId: string | null; position: number; beforeKey: string | null; depth: number; invalid?: boolean }
type DragState = {
  pointerId: number; row: Row; startX: number; startY: number; x: number; y: number;
  width: number; height: number; path: Array<{ x: number; y: number }>; target: DropTarget | null; valid: boolean
}
type ComposerState = 'closed' | 'opening' | 'open' | 'closing'

const chat = useChat()
const workspaces = useWorkspaces()
const { isMobile } = useSidebar()
const route = useRoute()
const router = useRouter()
const tree = ref<ProjectTreeData>({ folders: [], sessions: [] })
const loading = ref(false)
const error = ref<string | null>(null)
const collapsed = ref(new Set<string>())
const editingKey = ref<string | null>(null)
const titleDraft = ref('')
const treeElement = ref<HTMLElement | null>(null)
const drag = ref<DragState | null>(null)
const addFolderButton = ref<HTMLElement | null>(null)
const folderCard = ref<HTMLElement | null>(null)
const folderDetails = ref<HTMLElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
const composerState = ref<ComposerState>('closed')
const folderName = ref('')
const folderError = ref<string | null>(null)
const creatingFolder = ref(false)
const folderCardStyle = ref({ left: '0px', top: '0px', width: '252px' })
let folderAnimation: Animation | null = null
let folderDetailsAnimation: Animation | null = null
let folderTransitionId = 0
let loadVersion = 0

function children(parentId: string | null): Row[] {
  const folders = tree.value.folders.filter(item => item.parent_id === parentId).map<Row>(item => ({
    key: `folder:${item.id}`, kind: 'folder', id: item.id, parentId, title: item.name, depth: 0, position: item.position,
  }))
  const sessions = tree.value.sessions.filter(item => item.folder_id === parentId).map<Row>(item => ({
    key: `session:${item.session_id}`, kind: 'session', id: item.session_id, parentId,
    title: item.title.trim() || 'New Chat', depth: 0, position: item.position,
  }))
  return [...folders, ...sessions].sort((a, b) => a.position - b.position || a.key.localeCompare(b.key))
}

const rows = computed(() => {
  const result: Row[] = []
  const visit = (parentId: string | null, depth: number) => {
    for (const item of children(parentId)) {
      item.depth = depth
      result.push(item)
      if (item.kind === 'folder' && !collapsed.value.has(item.id)) visit(item.id, depth + 1)
    }
  }
  visit(null, 0)
  return result
})

async function load() {
  const workspaceId = workspaces.currentId.value
  if (!workspaceId) return
  const version = ++loadVersion
  loading.value = true
  try {
    const data = await loadProjectTree(workspaceId)
    if (version !== loadVersion) return
    tree.value = data
    chat.sessions.value = data.sessions
    error.value = null
  } catch (cause) {
    if (version === loadVersion) error.value = `项目目录加载失败：${cause instanceof Error ? cause.message : '未知错误'}`
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

function toggle(folderId: string) {
  const next = new Set(collapsed.value)
  if (next.has(folderId)) next.delete(folderId); else next.add(folderId)
  collapsed.value = next
  try { localStorage.setItem(`project-folders:${workspaces.currentId.value}`, JSON.stringify([...next])) } catch { /* optional preference */ }
}

function restoreCollapsed() {
  try { collapsed.value = new Set(JSON.parse(localStorage.getItem(`project-folders:${workspaces.currentId.value}`) ?? '[]') as string[]) }
  catch { collapsed.value = new Set() }
}

function openSession(id: string) {
  if (chat.isLoading.value) return
  void chat.selectSession(id)
  if (route.path !== '/chat') void router.push('/chat')
}

function newChat() {
  if (chat.isLoading.value || chat.isRestoring.value || chat.isUploading.value) return
  chat.reset()
  if (route.path !== '/chat') void router.push('/chat')
}

function reducedMotion() { return window.matchMedia('(prefers-reduced-motion: reduce)').matches }
function cancelFolderAnimation() {
  folderTransitionId += 1
  folderAnimation?.cancel()
  folderDetailsAnimation?.cancel()
  folderAnimation = null
  folderDetailsAnimation = null
}

async function openFolderComposer() {
  cancelFolderAnimation()
  const id = folderTransitionId
  const origin = addFolderButton.value?.getBoundingClientRect()
  if (!origin) return
  const width = Math.min(288, window.innerWidth - 24)
  folderCardStyle.value = {
    left: `${Math.max(12, Math.min(origin.right - width, window.innerWidth - width - 12))}px`,
    top: `${Math.max(12, Math.min(origin.top, window.innerHeight - 190))}px`,
    width: `${width}px`,
  }
  folderName.value = ''
  folderError.value = null
  composerState.value = 'opening'
  await nextTick()
  const card = folderCard.value
  const destination = card?.getBoundingClientRect()
  if (!card || !destination || reducedMotion()) {
    if (id === folderTransitionId) { composerState.value = 'open'; folderInput.value?.focus() }
    return
  }
  const offsetX = origin.left + origin.width / 2 - (destination.left + destination.width / 2)
  const offsetY = origin.top + origin.height / 2 - (destination.top + destination.height / 2)
  folderAnimation = card.animate([
    { transform: `translate(${offsetX}px, ${offsetY}px) scale(${origin.width / destination.width}, ${origin.height / destination.height})`, transformOrigin: 'top right', borderRadius: '999px', opacity: .82 },
    { transform: 'translate(0) scale(1)', transformOrigin: 'top right', borderRadius: '18px', opacity: 1 },
  ], { duration: 480, easing: 'cubic-bezier(.22,1,.36,1)', composite: 'replace' })
  try { await folderAnimation.finished } catch { return }
  if (id === folderTransitionId) { folderAnimation = null; composerState.value = 'open'; folderInput.value?.focus() }
}

async function closeFolderComposer() {
  if (creatingFolder.value) return
  cancelFolderAnimation()
  const id = folderTransitionId
  composerState.value = 'closing'
  if (!reducedMotion() && folderDetails.value) {
    folderDetailsAnimation = folderDetails.value.animate(
      [{ opacity: 1, transform: 'translateY(0)' }, { opacity: 0, transform: 'translateY(-5px)' }],
      { duration: 160, easing: 'cubic-bezier(.4,0,.6,1)', fill: 'forwards' },
    )
    try { await folderDetailsAnimation.finished } catch { return }
    folderDetailsAnimation = null
  }
  if (id !== folderTransitionId) return
  const origin = addFolderButton.value?.getBoundingClientRect()
  const card = folderCard.value
  const from = card?.getBoundingClientRect()
  if (!origin || !card || !from || reducedMotion()) {
    if (id === folderTransitionId) composerState.value = 'closed'
    return
  }
  const offsetX = origin.left + origin.width / 2 - (from.left + from.width / 2)
  const offsetY = origin.top + origin.height / 2 - (from.top + from.height / 2)
  folderAnimation = card.animate([
    { transform: 'translate(0) scale(1)', transformOrigin: 'top right', borderRadius: '18px', opacity: 1 },
    { transform: `translate(${offsetX}px, ${offsetY}px) scale(${origin.width / from.width}, ${origin.height / from.height})`, transformOrigin: 'top right', borderRadius: '999px', opacity: .82 },
  ], { duration: 400, easing: 'cubic-bezier(.4,0,.2,1)', composite: 'replace' })
  try { await folderAnimation.finished } catch { return }
  if (id === folderTransitionId) { folderAnimation = null; composerState.value = 'closed' }
}

async function addFolder() {
  const name = folderName.value.trim()
  const workspaceId = workspaces.currentId.value
  if (!name || !workspaceId) return
  creatingFolder.value = true
  folderError.value = null
  try { await createProjectFolder(workspaceId, name); await load(); creatingFolder.value = false; await closeFolderComposer() }
  catch (cause) { creatingFolder.value = false; folderError.value = `创建失败：${cause instanceof Error ? cause.message : '未知错误'}` }
}

function startRename(row: Row) {
  editingKey.value = row.key
  titleDraft.value = row.title
  void nextTick(() => document.querySelector<HTMLInputElement>('[data-project-title-input]')?.select())
}

async function saveRename(row: Row) {
  if (editingKey.value !== row.key) return
  editingKey.value = null
  const name = titleDraft.value.trim()
  const workspaceId = workspaces.currentId.value
  if (!name || !workspaceId) return
  try {
    if (row.kind === 'session') await chat.renameSession(row.id, name)
    else await renameProjectFolder(workspaceId, row.id, name)
    await load()
  } catch (cause) { error.value = `重命名失败：${cause instanceof Error ? cause.message : '未知错误'}` }
}

async function removeSession(id: string) {
  if (!window.confirm('删除这个会话的聊天记录和 Token Usage？已上传文件与向量索引不会删除。')) return
  await chat.deleteSession(id)
  await load()
}

function isDescendant(folderId: string | null, ancestorId: string) {
  let current = folderId
  while (current) {
    if (current === ancestorId) return true
    current = tree.value.folders.find(item => item.id === current)?.parent_id ?? null
  }
  return false
}

function targetForPoint(x: number, y: number, dragged: Row, current: DropTarget | null): DropTarget | null {
  const bounds = treeElement.value?.getBoundingClientRect()
  if (!bounds || x < bounds.left || x > bounds.right || y < bounds.top || y > bounds.bottom) return null
  const element = document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-project-row]')
  if (!element || !treeElement.value?.contains(element)) return current
  const hovered = rows.value.find(item => item.key === element.dataset.projectRow)
  if (!hovered || hovered.key === dragged.key) return current
  const rect = element.getBoundingClientRect()
  const intoFolder = hovered.kind === 'folder' && x > rect.left + 36 && y > rect.top + rect.height * 0.25 && y < rect.bottom - rect.height * 0.15
  const parentId = intoFolder ? hovered.id : hovered.parentId
  const siblings = children(parentId).filter(item => item.key !== dragged.key)
  const hoveredIndex = siblings.findIndex(item => item.key === hovered.key)
  const position = intoFolder ? 0 : Math.max(0, hoveredIndex + (y > rect.top + rect.height / 2 ? 1 : 0))
  const invalidCycle = dragged.kind === 'folder' && isDescendant(parentId, dragged.id)
  const hoveredFlatIndex = rows.value.findIndex(item => item.key === hovered.key)
  const firstChild = intoFolder ? rows.value[hoveredFlatIndex + 1] : null
  const beforeKey = intoFolder && firstChild?.depth === hovered.depth + 1 ? firstChild.key
    : intoFolder ? (rows.value[hoveredFlatIndex + 1]?.key ?? null)
      : (siblings[position]?.key ?? null)
  return { parentId, position, beforeKey, depth: intoFolder ? hovered.depth + 1 : hovered.depth, invalid: invalidCycle }
}

function beginDrag(event: PointerEvent, row: Row) {
  if (event.button !== 0 || drag.value) return
  const element = (event.currentTarget as HTMLElement).closest<HTMLElement>('[data-project-row]')
  if (!element) return
  const rect = element.getBoundingClientRect()
  drag.value = {
    pointerId: event.pointerId, row, startX: rect.left, startY: rect.top, x: event.clientX, y: event.clientY,
    width: rect.width, height: rect.height, path: [{ x: event.clientX, y: event.clientY }],
    target: { parentId: row.parentId, position: Math.max(0, children(row.parentId).findIndex(item => item.key === row.key)), beforeKey: row.key, depth: row.depth }, valid: true,
  }
  window.addEventListener('pointermove', onDragMove, { passive: false })
  window.addEventListener('pointerup', finishDrag)
  window.addEventListener('pointercancel', cancelDrag)
  event.preventDefault()
}

function onDragMove(event: PointerEvent) {
  const state = drag.value
  if (!state || event.pointerId !== state.pointerId) return
  state.x = event.clientX; state.y = event.clientY
  if (state.path.length < 80) state.path.push({ x: event.clientX, y: event.clientY })
  const target = targetForPoint(event.clientX, event.clientY, state.row, state.target)
  state.target = target
  state.valid = Boolean(target) && !target?.invalid
  const bounds = treeElement.value?.getBoundingClientRect()
  if (bounds && treeElement.value) {
    if (event.clientY < bounds.top + 30) treeElement.value.scrollTop -= 8
    else if (event.clientY > bounds.bottom - 30) treeElement.value.scrollTop += 8
  }
  event.preventDefault()
}

function detachDragListeners() {
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', finishDrag)
  window.removeEventListener('pointercancel', cancelDrag)
}

async function snapBack(state: DragState) {
  const ghost = document.querySelector<HTMLElement>('[data-project-ghost]')
  if (!ghost || matchMedia('(prefers-reduced-motion: reduce)').matches) return
  const points = [...state.path].reverse().filter((_, index) => index % Math.max(1, Math.floor(state.path.length / 12)) === 0)
  points.push({ x: state.startX, y: state.startY })
  await ghost.animate(points.map(point => ({ left: `${point.x + 8}px`, top: `${point.y + 8}px` })), { duration: 220, easing: 'ease-out' }).finished.catch(() => undefined)
}

async function finishDrag(event: PointerEvent) {
  const state = drag.value
  if (!state || event.pointerId !== state.pointerId) return
  detachDragListeners()
  const workspaceId = workspaces.currentId.value
  if (!state.valid || !state.target || !workspaceId) { await snapBack(state); drag.value = null; return }
  try {
    tree.value = await moveProjectItem(workspaceId, state.row.kind, state.row.id, state.target.parentId, state.target.position)
    chat.sessions.value = tree.value.sessions
    error.value = null
  } catch (cause) {
    error.value = `移动失败：${cause instanceof Error ? cause.message : '未知错误'}`
    await snapBack(state)
  } finally { drag.value = null }
}

async function cancelDrag() {
  const state = drag.value
  detachDragListeners()
  if (state) await snapBack(state)
  drag.value = null
}

async function keyboardMove(row: Row, offset: number) {
  const workspaceId = workspaces.currentId.value
  const siblings = children(row.parentId)
  const current = siblings.findIndex(item => item.key === row.key)
  if (!workspaceId || current < 0) return
  const next = Math.max(0, Math.min(siblings.length - 1, current + offset))
  if (next === current) return
  try { tree.value = await moveProjectItem(workspaceId, row.kind, row.id, row.parentId, next) }
  catch (cause) { error.value = `移动失败：${cause instanceof Error ? cause.message : '未知错误'}` }
}

watch(workspaces.currentId, () => { restoreCollapsed(); void load() }, { immediate: true })
watch(() => chat.sessions.value.map(item => `${item.session_id}:${item.title}:${item.updated_at}`).join('|'), () => { if (!loading.value) void load() })
onBeforeUnmount(() => { detachDragListeners(); cancelFolderAnimation() })
</script>

<template>
  <section class="min-h-0" aria-label="项目目录">
    <div class="flex items-center justify-between px-2 pb-1">
      <span class="text-[11px] font-medium uppercase tracking-wide text-sidebar-foreground/45">项目</span>
      <div class="flex items-center gap-0.5">
        <button ref="addFolderButton" type="button" class="rounded p-1 text-sidebar-foreground/55 hover:bg-sidebar-accent hover:text-sidebar-foreground" :class="composerState !== 'closed' ? 'invisible' : ''" title="新建项目" aria-label="新建项目" @click="openFolderComposer"><FolderPlus class="size-3.5" /></button>
        <button type="button" class="rounded p-1 text-sidebar-foreground/55 hover:bg-sidebar-accent hover:text-sidebar-foreground" title="新聊天" aria-label="新聊天" @click="newChat"><Plus class="size-3.5" /></button>
      </div>
    </div>
    <p v-if="error" class="px-2 py-1 text-xs text-red-300">{{ error }}</p>
    <div ref="treeElement" class="relative max-h-[45vh] min-h-12 overflow-y-auto px-1 pb-2" @dragstart.prevent>
      <div v-if="loading && !rows.length" class="space-y-2 px-2 py-1"><div v-for="n in 3" :key="n" class="h-7 animate-pulse rounded bg-white/5" /></div>
      <p v-else-if="!rows.length" class="px-2 py-2 text-xs text-sidebar-foreground/45">暂无项目内容</p>
      <template v-for="row in rows" :key="row.key">
        <DragPlaceholder v-if="drag?.target?.beforeKey === row.key" :depth="drag.target.depth" :height="drag.height" :valid="drag.valid" />
        <div :data-project-row="row.key" class="group flex h-8 min-w-0 items-center rounded-md text-sidebar-foreground/75 transition-[background-color,opacity] hover:bg-sidebar-accent/60"
          :class="[row.kind === 'session' && chat.sessionId.value === row.id && route.path === '/chat' ? 'bg-sidebar-accent text-sidebar-accent-foreground' : '', drag?.row.key === row.key ? 'invisible pointer-events-none' : '']"
          :style="{ paddingLeft: `${row.depth * 14 + 2}px` }" tabindex="0"
          @keydown.alt.up.prevent="keyboardMove(row, -1)" @keydown.alt.down.prevent="keyboardMove(row, 1)"
          @keydown.right.prevent="row.kind === 'folder' && collapsed.has(row.id) && toggle(row.id)"
          @keydown.left.prevent="row.kind === 'folder' && !collapsed.has(row.id) && toggle(row.id)">
          <button type="button" class="flex size-6 shrink-0 touch-none items-center justify-center cursor-grab text-sidebar-foreground/35 active:cursor-grabbing" aria-label="拖动排序" @pointerdown="beginDrag($event, row)"><GripVertical class="size-3.5" /></button>
          <button v-if="row.kind === 'folder'" type="button" class="flex size-5 shrink-0 items-center justify-center" :aria-label="collapsed.has(row.id) ? '展开文件夹' : '收起文件夹'" @click="toggle(row.id)">
            <ChevronRight v-if="collapsed.has(row.id)" class="size-3.5" /><ChevronDown v-else class="size-3.5" />
          </button>
          <Folder v-if="row.kind === 'folder'" class="mr-1 size-3.5 shrink-0 text-amber-300/70" />
          <MessageSquare v-else class="mr-1 size-3.5 shrink-0 text-sidebar-foreground/45" />
          <input v-if="editingKey === row.key" v-model="titleDraft" data-project-title-input maxlength="100" class="min-w-0 flex-1 rounded border border-white/15 bg-[#20242b] px-1 text-[13px] outline-none" @keydown.enter.prevent="saveRename(row)" @keydown.esc.prevent="editingKey = null" @blur="saveRename(row)" />
          <button v-else type="button" class="min-w-0 flex-1 truncate py-1 text-left text-[13px]" :title="row.title" @click="row.kind === 'folder' ? toggle(row.id) : openSession(row.id)">{{ row.title }}</button>
          <Popover>
            <PopoverTrigger as-child><button type="button" class="mr-1 rounded p-1 opacity-0 hover:bg-white/10 group-hover:opacity-100 focus:opacity-100" :aria-label="`${row.title} 操作`"><MoreHorizontal class="size-3.5" /></button></PopoverTrigger>
            <PopoverContent side="right" align="start" class="w-28 border-white/10 bg-[#171a20] p-1 text-white">
              <button type="button" class="w-full rounded px-3 py-1.5 text-left text-sm hover:bg-white/10" @click="startRename(row)">重命名</button>
              <button v-if="row.kind === 'session'" type="button" class="w-full rounded px-3 py-1.5 text-left text-sm text-red-300 hover:bg-white/10" @click="removeSession(row.id)">删除</button>
            </PopoverContent>
          </Popover>
        </div>
      </template>
      <DragPlaceholder v-if="drag?.target && drag.target.beforeKey === null" :depth="drag.target.depth" :height="drag.height" :valid="drag.valid" />
    </div>
    <div v-if="drag" data-project-ghost class="pointer-events-none fixed z-50 flex h-8 items-center gap-2 rounded-md border px-2 text-xs shadow-xl backdrop-blur"
      :class="drag.valid ? 'border-sky-400/40 bg-[#171a20]/95 text-white' : 'border-red-400/50 bg-red-950/90 text-red-100'"
      :style="{ left: `${drag.x + 8}px`, top: `${drag.y + 8}px`, width: `${Math.min(drag.width, 260)}px` }">
      <Folder v-if="drag.row.kind === 'folder'" class="size-3.5" /><MessageSquare v-else class="size-3.5" />
      <span class="truncate">{{ drag.row.title }}</span>
    </div>
    <Teleport v-if="composerState !== 'closed'" :to="isMobile ? '[data-project-portal]' : 'body'">
      <section ref="folderCard" class="pointer-events-auto fixed z-[100] overflow-hidden rounded-[18px] border border-white/12 bg-[#15181e]/98 text-white shadow-[0_24px_70px_rgba(0,0,0,.52)] backdrop-blur-xl" :style="folderCardStyle">
        <header class="flex items-center justify-between border-b border-white/[.08] px-4 py-3">
          <div><div class="text-sm font-medium text-white/90">新建项目</div><div class="mt-0.5 text-[11px] text-white/38">将相关对话整理到同一目录</div></div>
          <button type="button" class="rounded-lg px-2 py-1 text-xs text-white/45 hover:bg-white/[.07] hover:text-white/80" @click="closeFolderComposer">取消</button>
        </header>
        <form ref="folderDetails" class="p-4" :class="composerState === 'opening' ? 'folder-details-enter' : ''" @submit.prevent="addFolder">
          <label class="block text-[11px] text-white/50" for="project-folder-name">项目名称</label>
          <input id="project-folder-name" ref="folderInput" v-model="folderName" maxlength="100" autocomplete="off" class="mt-2 h-9 w-full rounded-lg border border-white/12 bg-white/[.045] px-3 text-sm text-white outline-none transition-colors placeholder:text-white/25 focus:border-sky-300/45" placeholder="例如：Agent 实验" @keydown.esc.prevent="closeFolderComposer" />
          <p v-if="folderError" class="mt-2 text-xs text-red-300">{{ folderError }}</p>
          <div class="mt-4 flex justify-end gap-2">
            <button type="button" class="rounded-lg px-3 py-1.5 text-xs text-white/50 hover:bg-white/[.07]" :disabled="creatingFolder" @click="closeFolderComposer">取消</button>
            <button type="submit" class="rounded-lg bg-white px-3 py-1.5 text-xs font-medium text-[#111318] transition-opacity disabled:opacity-35" :disabled="!folderName.trim() || creatingFolder">{{ creatingFolder ? '创建中…' : '创建' }}</button>
          </div>
        </form>
      </section>
    </Teleport>
  </section>
</template>

<style scoped>
.folder-details-enter { animation: folder-details-in 220ms 190ms cubic-bezier(.22,1,.36,1) both; }
@keyframes folder-details-in { from { opacity: 0; transform: translateY(-5px); } to { opacity: 1; transform: translateY(0); } }
@media (prefers-reduced-motion: reduce) { .folder-details-enter { animation: none; } }
</style>
