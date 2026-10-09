export type ProjectFolder = {
  id: string
  workspace_id: string
  parent_id: string | null
  name: string
  position: number
  created_at: string
  updated_at: string
}

export type ProjectSession = {
  session_id: string
  title: string
  updated_at: string
  folder_id: string | null
  position: number
}

export type ProjectTreeData = { folders: ProjectFolder[]; sessions: ProjectSession[] }
export type ProjectItemType = 'folder' | 'session'

function apiBase() { return import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000' }

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(payload?.detail ?? `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export async function loadProjectTree(workspaceId: string) {
  return json<ProjectTreeData>(await fetch(`${apiBase()}/projects/tree?workspace_id=${encodeURIComponent(workspaceId)}`))
}

export async function createProjectFolder(workspaceId: string, name: string, parentId: string | null = null) {
  return json<ProjectFolder>(await fetch(`${apiBase()}/projects/folders`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace_id: workspaceId, name, parent_id: parentId }),
  }))
}

export async function renameProjectFolder(workspaceId: string, folderId: string, name: string) {
  return json<ProjectFolder>(await fetch(`${apiBase()}/projects/folders/${encodeURIComponent(folderId)}?workspace_id=${encodeURIComponent(workspaceId)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
  }))
}

export async function moveProjectItem(workspaceId: string, itemType: ProjectItemType, itemId: string, parentId: string | null, position: number) {
  return json<ProjectTreeData>(await fetch(`${apiBase()}/projects/move`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace_id: workspaceId, item_type: itemType, item_id: itemId, parent_id: parentId, position }),
  }))
}
