// Independent loopback-only UI acceptance server. All records are disposable synthetic data.
// Run from frontend: node tests/memory-browser-harness.mjs; open http://127.0.0.1:5178/settings.
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'

const tools = { web_search: false, image_generation: false, data_analysis: false, think_mode: false }
const workspaces = ['a', 'b'].map((id, index) => ({ id, name: `Memory Browser ${id.toUpperCase()}`, description: '',
  system_prompt: '', default_model_id: null, tool_settings: tools, is_default: index === 0,
  created_at: '2026-10-21T00:00:00Z', updated_at: '2026-10-21T00:00:00Z' }))
let rows = [], enabled = true, conflictOnce = false, serial = 0
let holdNextList = false, pendingList = null
const writes = []
const server = createServer(async (request, response) => {
  response.setHeader('Access-Control-Allow-Origin', 'http://127.0.0.1:5178')
  response.setHeader('Access-Control-Allow-Headers', 'Content-Type')
  response.setHeader('Access-Control-Allow-Methods', 'GET, POST, PATCH, DELETE, OPTIONS')
  if (request.method === 'OPTIONS') { response.writeHead(204).end(); return }
  const url = new URL(request.url, 'http://127.0.0.1:18765')
  const send = (data, status = 200) => { response.writeHead(status, { 'Content-Type': 'application/json' }).end(status === 204 ? undefined : JSON.stringify(data)) }
  let text = ''
  for await (const chunk of request) text += chunk
  const body = text ? JSON.parse(text) : {}
  if (url.pathname === '/__test/state') {
    if (request.method === 'POST') {
      if ('enabled' in body) enabled = body.enabled
      if ('conflictOnce' in body) conflictOnce = body.conflictOnce
      if ('holdNextList' in body) holdNextList = body.holdNextList
      if (body.releaseList && pendingList) { pendingList(); pendingList = null }
    }
    send({ rows, enabled, writes, heldList: !!pendingList }); return
  }
  if (url.pathname === '/workspaces') { send(workspaces); return }
  if (url.pathname === '/models') { send({ models: [] }); return }
  if (url.pathname === '/projects/tree') { send({ folders: [], sessions: [] }); return }
  if (url.pathname === '/agent-runs/latest') { send(null); return }
  if (url.pathname === '/memory/maintenance/orphans') {
    send({ orphans: [{ workspace_id: 'synthetic-deleted', count: 2 }], record_count: 2, action: 'retain', atomic_snapshot: false }); return
  }
  const match = /^\/workspaces\/(a|b)\/memories(?:\/([^/]+))?$/.exec(url.pathname)
  if (!match) { send([]); return }
  if (!enabled) { send({}, 503); return }
  const [, workspace, id] = match
  if (request.method === 'GET') {
    const snapshot = structuredClone(rows.filter(row => row.workspace_id === workspace))
    if (holdNextList) { holdNextList = false; pendingList = () => send(snapshot); return }
    send(snapshot); return
  }
  writes.push({ method: request.method, workspace, id, body, expected_version: url.searchParams.get('expected_version') })
  const row = rows.find(item => item.workspace_id === workspace && item.id === id)
  if (request.method === 'POST') {
    if (body.confirmed !== true) { send({}, 422); return }
    const existing = rows.find(item => item.workspace_id === workspace && item.key === body.key)
    if (existing) { send(existing, existing.value === body.value ? 200 : 409); return }
    const item = { id: `synthetic-${++serial}`, workspace_id: workspace, key: body.key, value: body.value,
      version: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
    rows.push(item); send(item); return
  }
  if (!row) { send({}, 404); return }
  if (request.method === 'PATCH') {
    if (conflictOnce) {
      conflictOnce = false; row.version++; row.value = 'synthetic concurrent update'; send({}, 409); return
    }
    if (body.expected_version !== row.version) { send({}, 409); return }
    row.value = body.value; row.version++; row.updated_at = new Date().toISOString(); send(row); return
  }
  if (Number(url.searchParams.get('expected_version')) !== row.version) { send({}, 409); return }
  rows = rows.filter(item => item !== row); send(null, 204)
})
server.listen(18765, '127.0.0.1', () => console.log('Synthetic Memory API: 127.0.0.1:18765'))
const vite = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5178', '--strictPort'], {
  stdio: 'inherit', env: { ...process.env, VITE_API_BASE_URL: 'http://127.0.0.1:18765' },
})
function stop() { vite.kill(); server.close(); process.exit() }
process.on('SIGINT', stop)
process.on('SIGTERM', stop)
vite.on('exit', () => { server.close(); process.exit() })
