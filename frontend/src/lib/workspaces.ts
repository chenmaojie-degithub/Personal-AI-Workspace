import { computed, ref } from 'vue'

export type WorkspaceTools = {
  web_search: boolean
  image_generation: boolean
  data_analysis: boolean
  think_mode: boolean
}

export type Workspace = {
  id: string
  name: string
  description: string
  system_prompt: string
  default_model_id: string | null
  tool_settings: WorkspaceTools
  created_at: string
  updated_at: string
  is_default: boolean
}

export type WorkspaceInput = Pick<Workspace, 'name' | 'description' | 'system_prompt' | 'default_model_id'> & { tool_settings?: WorkspaceTools }

const KEY = 'ai_workspace_workspace_id'
const items = ref<Workspace[]>([])
const currentId = ref<string | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const current = computed(() => items.value.find(item => item.id === currentId.value) ?? null)
let loaded = false
let pending: Promise<void> | null = null

function apiBase() { return import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000' }
function remember(id: string) {
  currentId.value = id
  try { localStorage.setItem(KEY, id) } catch { /* This tab remains usable. */ }
}

async function refresh() {
  loading.value = true
  try {
    const response = await fetch(`${apiBase()}/workspaces`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    items.value = await response.json() as Workspace[]
    let saved: string | null = null
    try { saved = localStorage.getItem(KEY) } catch { /* Storage may be unavailable. */ }
    const selected = items.value.find(item => item.id === currentId.value)
      ?? items.value.find(item => item.id === saved)
      ?? items.value.find(item => item.is_default)
      ?? items.value[0]
    if (selected) remember(selected.id)
    error.value = null
    loaded = true
  } catch (cause) {
    error.value = `工作区加载失败：${cause instanceof Error ? cause.message : '未知错误'}`
    throw cause
  } finally {
    loading.value = false
  }
}

function ensureLoaded() {
  if (loaded) return Promise.resolve()
  if (!pending) pending = refresh().finally(() => { pending = null })
  return pending
}

function select(id: string) {
  if (!items.value.some(item => item.id === id)) return false
  remember(id)
  return true
}

async function create(input: WorkspaceInput) {
  const response = await fetch(`${apiBase()}/workspaces`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!response.ok) throw new Error(`创建失败：HTTP ${response.status}`)
  const workspace = await response.json() as Workspace
  items.value = [...items.value, workspace]
  remember(workspace.id)
  return workspace
}

async function update(id: string, changes: Partial<WorkspaceInput>) {
  const response = await fetch(`${apiBase()}/workspaces/${encodeURIComponent(id)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
  })
  if (!response.ok) throw new Error(`保存失败：HTTP ${response.status}`)
  const workspace = await response.json() as Workspace
  items.value = items.value.map(item => item.id === id ? workspace : item)
  return workspace
}

async function remove(id: string) {
  const response = await fetch(`${apiBase()}/workspaces/${encodeURIComponent(id)}`, { method: 'DELETE' })
  if (!response.ok) throw new Error(`删除失败：HTTP ${response.status}`)
  items.value = items.value.filter(item => item.id !== id)
  const fallback = items.value.find(item => item.is_default) ?? items.value[0]
  if (fallback) remember(fallback.id)
}

export function useWorkspaces() {
  return { items, currentId, current, loading, error, ensureLoaded, refresh, select, create, update, remove }
}
