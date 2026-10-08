import { computed, reactive, ref, watch } from 'vue'
import { useWorkspaces } from '@/lib/workspaces'

export type ChatRole = 'user' | 'assistant' | 'system' | 'tool'

export type TransportChatMessage = {
  role: ChatRole
  content: string
}

export type UiAttachmentStatus = 'uploading' | 'uploaded' | 'warning' | 'error'

export type UiAttachment = {
  id: string
  filename: string
  bytes?: number
  contentType?: string
  status: UiAttachmentStatus
  detail?: string | null
}

export type UiChatMessage = TransportChatMessage & {
  attachments?: UiAttachment[]
  sources?: CitationSource[]
  usage?: LLMUsage | null
  incomplete?: boolean
  charts?: ChartArtifact[]
}

export type ChartArtifact = { url: string; title: string }

export type CitationSource = {
  type: 'knowledge' | 'web'
  title: string | null
  url: string | null
  filename: string | null
  document_id: string | null
  chunk_index: number | null
  page_number: number | null
  section: string | null
  content_preview: string | null
  distance: number | null
}

export type AgentStep = {
  step_index: number
  title: string
  tool_name?: string | null
  status: string
  output_preview?: string | null
  error?: string | null
}

export type AgentRun = {
  id: string
  goal: string
  status: string
  plan: Array<{ index: number; title: string; status: string }>
  steps: AgentStep[]
  error?: string | null
}

export type LLMUsage = {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export type AvailableModel = {
  model_id: string
  provider: string
  model: string
  supports_tools: boolean
}

export type StoredSession = {
  session_id: string
  title: string
  updated_at: string
}

export type ToolCallLog = {
  name: string
  input?: Record<string, unknown>
  output_preview?: string
  error?: string | null
}

export type ChatResponse = {
  session_id: string
  assistant_message?: TransportChatMessage | null
  tool_calls?: ToolCallLog[]
  charts?: ChartArtifact[]
  error?: string | null
}

const SESSION_KEY = 'ai_workspace_session_id'
const MODEL_KEY = 'ai_workspace_model_id'
const SESSION_PATTERN = /^[A-Za-z0-9_-]{1,128}$/

function readLocal(key: string): string | null {
  try { return localStorage.getItem(key) } catch { return null }
}

function writeLocal(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* Storage can be unavailable; keep this tab usable. */ }
}

function createSessionId(): string {
  const sessionId = crypto.randomUUID()
  writeLocal(SESSION_KEY, sessionId)
  return sessionId
}

function loadSessionId(): string {
  const saved = readLocal(SESSION_KEY)
  return saved && SESSION_PATTERN.test(saved) ? saved : createSessionId()
}

function apiBaseUrl() {
  // Optional: you can set VITE_API_BASE_URL in your local env.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const env = (import.meta as any).env as Record<string, string | undefined>
  return env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
}

let sharedChat: ReturnType<typeof createChat> | null = null

export function useChat() {
  return sharedChat ??= createChat()
}

function createChat() {
  const workspaces = useWorkspaces()

  const sessionId = ref(loadSessionId())
  const messages = ref<UiChatMessage[]>([])

  const toolCalls = ref<ToolCallLog[]>([])
  const agentRun = ref<AgentRun | null>(null)
  const isLoading = ref(false)
  const isUploading = ref(false)
  const isRestoring = ref(false)
  const lastError = ref<string | null>(null)
  const availableModels = ref<AvailableModel[]>([])
  const selectedModelId = ref<string | null>(readLocal(MODEL_KEY))
  const sessions = ref<StoredSession[]>([])
  const sessionsError = ref<string | null>(null)
  const isLoadingSessions = ref(true)
  let controller: AbortController | null = null
  let restoreVersion = 0
  let sessionsVersion = 0

  const canSend = computed(() => !isLoading.value && !isRestoring.value)

  watch(selectedModelId, (modelId) => {
    if (modelId) writeLocal(MODEL_KEY, modelId)
    else try { localStorage.removeItem(MODEL_KEY) } catch { /* Storage may be unavailable. */ }
  })

  async function loadHistory() {
    const version = ++restoreVersion
    const currentSession = sessionId.value
    isRestoring.value = true
    try {
      await workspaces.ensureLoaded()
      const res = await fetch(`${apiBaseUrl()}/sessions/${encodeURIComponent(currentSession)}/messages?workspace_id=${encodeURIComponent(workspaces.currentId.value ?? '')}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const history = await res.json() as Array<{ role: 'user' | 'assistant'; content: string }>
      if (version === restoreVersion && sessionId.value === currentSession) {
        messages.value = history.map(({ role, content }) => ({ role, content }))
        await loadAgentRun(currentSession)
      }
    } catch (e) {
      if (version === restoreVersion && sessionId.value === currentSession) {
        lastError.value = `Could not restore chat history: ${e instanceof Error ? e.message : 'Unknown error'}`
      }
    } finally {
      if (version === restoreVersion) isRestoring.value = false
    }
  }

  async function loadAgentRun(targetSession = sessionId.value) {
    const workspaceId = workspaces.currentId.value
    if (!workspaceId) return
    try {
      const response = await fetch(`${apiBaseUrl()}/agent-runs/latest?session_id=${encodeURIComponent(targetSession)}&workspace_id=${encodeURIComponent(workspaceId)}`)
      if (response.ok && sessionId.value === targetSession) agentRun.value = await response.json() as AgentRun | null
    } catch { /* Agent history is supplemental to chat restoration. */ }
  }

  async function loadSessions() {
    const version = ++sessionsVersion
    isLoadingSessions.value = true
    try {
      await workspaces.ensureLoaded()
      const res = await fetch(`${apiBaseUrl()}/sessions?workspace_id=${encodeURIComponent(workspaces.currentId.value ?? '')}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json() as StoredSession[]
      if (version === sessionsVersion) {
        sessions.value = data
        sessionsError.value = null
      }
    } catch (e) {
      if (version === sessionsVersion) {
        sessionsError.value = `历史记录加载失败：${e instanceof Error ? e.message : '未知错误'}`
      }
    } finally {
      if (version === sessionsVersion) isLoadingSessions.value = false
    }
  }

  async function deleteSession(selectedId: string): Promise<boolean> {
    if (isLoading.value || isRestoring.value || !SESSION_PATTERN.test(selectedId)) return false
    try {
      const res = await fetch(`${apiBaseUrl()}/sessions/${encodeURIComponent(selectedId)}?workspace_id=${encodeURIComponent(workspaces.currentId.value ?? '')}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      sessions.value = sessions.value.filter((item) => item.session_id !== selectedId)
      if (sessionId.value === selectedId) reset()
      await loadSessions()
      return true
    } catch (e) {
      sessionsError.value = `删除失败：${e instanceof Error ? e.message : '未知错误'}`
      return false
    }
  }

  async function renameSession(selectedId: string, title: string): Promise<boolean> {
    const trimmed = title.trim()
    if (!SESSION_PATTERN.test(selectedId) || !trimmed || trimmed.length > 100) return false
    try {
      await workspaces.ensureLoaded()
      const res = await fetch(`${apiBaseUrl()}/sessions/${encodeURIComponent(selectedId)}?workspace_id=${encodeURIComponent(workspaces.currentId.value ?? '')}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: trimmed }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const updated = await res.json() as StoredSession
      sessions.value = sessions.value.map((item) => item.session_id === selectedId ? updated : item)
      sessionsError.value = null
      return true
    } catch (e) {
      sessionsError.value = `重命名失败：${e instanceof Error ? e.message : '未知错误'}`
      return false
    }
  }

  async function selectSession(selectedId: string) {
    if (isLoading.value || !SESSION_PATTERN.test(selectedId) || selectedId === sessionId.value || !sessions.value.some(item => item.session_id === selectedId)) return
    sessionId.value = selectedId
    writeLocal(SESSION_KEY, selectedId)
    messages.value = []
    toolCalls.value = []
    lastError.value = null
    await loadHistory()
  }

  async function loadModels() {
    try {
      await workspaces.ensureLoaded()
      const res = await fetch(`${apiBaseUrl()}/models`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json() as { default_model_id: string | null; models: AvailableModel[] }
      availableModels.value = data.models
      if (!data.models.some((item) => item.model_id === selectedModelId.value)) {
        selectedModelId.value = data.models.find((item) => item.model_id === workspaces.current.value?.default_model_id)?.model_id
          ?? data.models.find((item) => item.model_id === data.default_model_id)?.model_id
          ?? data.models[0]?.model_id ?? null
      }
    } catch (e) {
      lastError.value = `Could not load models: ${e instanceof Error ? e.message : 'Unknown error'}`
    }
  }

  async function send(userText: string, opts?: { attachments?: UiAttachment[]; documentIds?: string[] }) {
    if (!userText.trim() || !canSend.value) return
    try { await workspaces.ensureLoaded() } catch { lastError.value = 'Workspace is unavailable'; return }

    lastError.value = null
    toolCalls.value = []
    agentRun.value = null
    isLoading.value = true

    messages.value.push({ role: 'user', content: userText, attachments: opts?.attachments })
    const requestMessages = messages.value
      .filter((m) => !m.incomplete)
      .map((m) => ({ role: m.role, content: m.content }))
    const assistant = reactive<UiChatMessage>({ role: 'assistant', content: '', sources: [], charts: [] })
    messages.value.push(assistant)
    controller = new AbortController()

    try {
      const res = await fetch(`${apiBaseUrl()}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          session_id: sessionId.value,
          workspace_id: workspaces.currentId.value,
          model_id: selectedModelId.value,
          document_ids: opts?.documentIds ?? [],
          messages: requestMessages,
        }),
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(`HTTP ${res.status}: ${text}`)
      }

      if (!res.body) throw new Error('Streaming response has no body')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let done = false

      function handleEvent(block: string) {
        const event = block.split('\n').find((line) => line.startsWith('event:'))?.slice(6).trim()
        const raw = block.split('\n').find((line) => line.startsWith('data:'))?.slice(5).trim()
        if (!event || !raw) return
        const data = JSON.parse(raw)
        if (event === 'message') assistant.content += data.content as string
        else if (event === 'source') assistant.sources?.push(data as CitationSource)
        else if (event === 'chart') {
          const chart = data as ChartArtifact
          assistant.charts?.push({ ...chart, url: new URL(chart.url, apiBaseUrl()).toString() })
        }
        else if (event === 'tool_call') toolCalls.value.push(data as ToolCallLog)
        else if (event === 'agent_run') {
          agentRun.value = { id: data.run_id as string, goal: data.goal as string, status: data.status as string, plan: [], steps: [] }
        }
        else if (event === 'agent_plan' && agentRun.value) {
          agentRun.value.plan = data.steps as AgentRun['plan']
          agentRun.value.status = 'running'
        }
        else if (event === 'agent_step' && agentRun.value) {
          const step: AgentStep = {
            step_index: data.index as number,
            title: data.title as string,
            tool_name: data.tool as string,
            status: data.status as string,
            error: data.error as string | undefined,
          }
          const index = agentRun.value.steps.findIndex(item => item.step_index === step.step_index)
          if (index === -1) agentRun.value.steps.push(step)
          else agentRun.value.steps[index] = step
        }
        else if (event === 'agent_status' && agentRun.value) {
          agentRun.value.status = data.status as string
          agentRun.value.error = data.reason as string | null
        }
        else if (event === 'usage') assistant.usage = data as LLMUsage | null
        else if (event === 'error') throw new Error(data.message as string)
        else if (event === 'done') {
          sessionId.value = data.session_id as string
          done = true
        }
      }

      while (!done) {
        const result = await reader.read()
        if (result.done) break
        buffer += decoder.decode(result.value, { stream: true })
        buffer = buffer.replace(/\r\n/g, '\n')
        let boundary = buffer.indexOf('\n\n')
        while (boundary !== -1) {
          handleEvent(buffer.slice(0, boundary))
          buffer = buffer.slice(boundary + 2)
          boundary = buffer.indexOf('\n\n')
        }
      }
      if (!done) throw new Error('Stream ended before done event; partial answer was not saved')
      if (!assistant.content) assistant.content = '(empty response)'
      await loadSessions()
    } catch (e) {
      const msg = e instanceof DOMException && e.name === 'AbortError'
        ? 'Generation stopped; this partial answer will not be sent as chat history.'
        : e instanceof Error ? e.message : 'Unknown error'
      lastError.value = msg
      assistant.incomplete = true
      if (!assistant.content) assistant.content = `Generation failed: ${msg}`
    } finally {
      controller = null
      isLoading.value = false
    }
  }

  function stop() {
    const runId = agentRun.value?.id
    controller?.abort()
    if (runId && workspaces.currentId.value) {
      agentRun.value!.status = 'cancelled'
      void fetch(`${apiBaseUrl()}/agent-runs/${encodeURIComponent(runId)}/cancel?workspace_id=${encodeURIComponent(workspaces.currentId.value)}`, { method: 'POST' })
    }
  }

  function reset() {
    if (isLoading.value || isRestoring.value) return
    sessionId.value = createSessionId()
    toolCalls.value = []
    agentRun.value = null
    lastError.value = null
    messages.value = []
  }

  async function switchWorkspace(id: string) {
    if (isLoading.value || isRestoring.value || !workspaces.select(id)) return false
    ++restoreVersion
    sessions.value = []
    isLoadingSessions.value = true
    sessionId.value = createSessionId()
    messages.value = []
    toolCalls.value = []
    agentRun.value = null
    lastError.value = null
    selectedModelId.value = workspaces.current.value?.default_model_id ?? null
    await Promise.all([loadModels(), loadSessions()])
    return true
  }

  return {
    sessionId,
    messages,
    toolCalls,
    agentRun,
    isLoading,
    isUploading,
    isRestoring,
    lastError,
    availableModels,
    selectedModelId,
    sessions,
    sessionsError,
    isLoadingSessions,
    canSend,
    loadModels,
    loadHistory,
    loadAgentRun,
    loadSessions,
    renameSession,
    deleteSession,
    selectSession,
    send,
    stop,
    reset,
    switchWorkspace,
  }
}
