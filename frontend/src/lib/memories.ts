import { onScopeDispose, ref, watch } from 'vue'
import type { Ref } from 'vue'

export type Memory = {
  id: string
  workspace_id: string
  key: string
  value: string
  version: number
  created_at: string
  updated_at: string
}
export type OrphanPreview = {
  orphans: { workspace_id: string; count: number }[]
  record_count: number
  action: 'retain'
  atomic_snapshot: false
}

function apiBase() { return import.meta.env?.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000' }

export function useMemories(workspaceId: Ref<string | null>) {
  const rows = ref<Memory[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const unavailable = ref(false)
  const error = ref('')
  const preview = ref<OrphanPreview | null>(null)
  const previewLoading = ref(false)
  let epoch = 0
  let listSequence = 0
  const controllers = new Set<AbortController>()
  const active = (id: string, generation: number) => workspaceId.value === id && epoch === generation
  function controller() {
    const item = new AbortController()
    controllers.add(item)
    return item
  }
  function url(id: string) { return `${apiBase()}/workspaces/${encodeURIComponent(id)}/memories` }
  function failure(status: number) {
    if (status === 503) {
      unavailable.value = true
      rows.value = []
      preview.value = null
      return 'Memory 未启用或存储暂不可用；此页面不会自动开启它，现有聊天仍可使用。'
    }
    if (status === 409) return '记忆已被修改或同名 key 冲突。已请求刷新列表；请核对最新版本后重新编辑，不会自动覆盖。'
    if (status === 404) { rows.value = []; return 'Workspace 或记忆已不存在，请刷新后重试。' }
    return `请求失败（HTTP ${status}），未自动重试。`
  }
  async function reload() {
    const id = workspaceId.value
    if (!id) return
    const generation = epoch, sequence = ++listSequence, request = controller()
    loading.value = true
    try {
      const response = await fetch(`${url(id)}?limit=200`, { signal: request.signal })
      if (!active(id, generation) || sequence !== listSequence) return
      if (!response.ok) { error.value = failure(response.status); return }
      const data = await response.json() as Memory[]
      if (!active(id, generation) || sequence !== listSequence) return
      rows.value = data
      unavailable.value = false
      error.value = ''
    } catch (cause) {
      if (active(id, generation) && sequence === listSequence && !request.signal.aborted) {
        error.value = '网络请求失败，请手动刷新；未自动重试。'
      }
    } finally {
      controllers.delete(request)
      if (active(id, generation) && sequence === listSequence) loading.value = false
    }
  }
  async function mutate(method: string, body?: object, row?: Memory): Promise<boolean> {
    const id = workspaceId.value
    if (!id || saving.value || loading.value || unavailable.value || (row && row.workspace_id !== id)) return false
    const generation = epoch, request = controller()
    saving.value = true
    error.value = ''
    try {
      let target = row ? `${url(id)}/${encodeURIComponent(row.id)}` : url(id)
      if (method === 'DELETE' && row) target += `?expected_version=${row.version}`
      const response = await fetch(target, { method, signal: request.signal,
        headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
      if (!active(id, generation)) return false
      if (!response.ok) {
        const message = failure(response.status)
        if (response.status === 409) await reload()
        if (active(id, generation)) error.value = message
        return false
      }
      await reload()
      return active(id, generation)
    } catch {
      if (active(id, generation) && !request.signal.aborted) error.value = '网络请求中断，操作结果未知。请先刷新核对，不要直接重复提交。'
      return false
    } finally {
      controllers.delete(request)
      if (active(id, generation)) saving.value = false
    }
  }
  async function inspectOrphans() {
    const id = workspaceId.value
    if (!id || previewLoading.value || unavailable.value) return
    const generation = epoch, request = controller()
    previewLoading.value = true
    try {
      const response = await fetch(`${apiBase()}/memory/maintenance/orphans`, { signal: request.signal })
      if (!active(id, generation)) return
      if (!response.ok) { error.value = '孤立记录预览不可用；未清理任何记录。'; return }
      const data = await response.json() as OrphanPreview
      if (active(id, generation)) preview.value = data
    } catch {
      if (active(id, generation) && !request.signal.aborted) error.value = '孤立记录预览失败；未清理任何记录。'
    } finally {
      controllers.delete(request)
      if (active(id, generation)) previewLoading.value = false
    }
  }
  function reset() {
    epoch++
    for (const request of controllers) request.abort()
    controllers.clear()
    rows.value = []
    preview.value = null
    loading.value = saving.value = previewLoading.value = unavailable.value = false
    error.value = ''
  }
  watch(workspaceId, () => { reset(); void reload() }, { immediate: true, flush: 'sync' })
  onScopeDispose(reset)
  return { rows, loading, saving, unavailable, error, preview, previewLoading, reload, inspectOrphans,
    create: (key: string, value: string, confirmed: boolean) => confirmed ? mutate('POST', { key, value, confirmed }) : Promise.resolve(false),
    update: (row: Memory, value: string, confirmed: boolean) => confirmed ? mutate('PATCH', { value, expected_version: row.version, confirmed }, row) : Promise.resolve(false),
    remove: (row: Memory, confirmed: boolean) => confirmed ? mutate('DELETE', undefined, row) : Promise.resolve(false),
  }
}
