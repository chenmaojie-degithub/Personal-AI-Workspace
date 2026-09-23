// Run against the local Vite and FastAPI servers with Edge CDP on port 9225.
// This smoke check sends one real chat request and stores test messages in the configured database.
const endpoint = 'http://127.0.0.1:9225'
const tab = await (await fetch(`${endpoint}/json/new?http://127.0.0.1:5173/chat`, { method: 'PUT' })).json()
const socket = new WebSocket(tab.webSocketDebuggerUrl)
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject })
let nextId = 0
const pending = new Map()
socket.onmessage = ({ data }) => {
  const message = JSON.parse(data)
  if (!message.id) return
  const waiter = pending.get(message.id)
  if (!waiter) return
  pending.delete(message.id)
  message.error ? waiter.reject(new Error(message.error.message)) : waiter.resolve(message.result)
}
function call(method, params = {}) {
  const id = ++nextId
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    socket.send(JSON.stringify({ id, method, params }))
  })
}
async function evaluate(expression) {
  const result = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text)
  return result.result.value
}
async function waitFor(expression, timeout = 10000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (await evaluate(expression)) return
    await new Promise((resolve) => setTimeout(resolve, 150))
  }
  throw new Error(`Timed out: ${expression}`)
}
const sessionKey = 'ai_workspace_session_id'
const modelKey = 'ai_workspace_model_id'
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
try {
  await call('Runtime.enable')
  await call('Page.enable')
  await waitFor("document.querySelector('button[aria-label=\"Chat model\"]:not(:disabled)')")
  if (process.argv[2] === 'verify-reopen') {
    const session = await evaluate(`localStorage.getItem('${sessionKey}')`)
    const model = await evaluate(`localStorage.getItem('${modelKey}')`)
    if (session !== process.argv[3] || model !== process.argv[4]) throw new Error('Browser reopen did not restore local state')
    console.log(JSON.stringify({ browserReopenRestored: true, session, model }))
    process.exitCode = 0
  } else if (process.argv[2] === 'verify-fallback') {
    const before = await evaluate(`localStorage.getItem('${sessionKey}')`)
    await evaluate(`localStorage.setItem('${modelKey}', 'removed-model'); localStorage.removeItem('${sessionKey}')`)
    await call('Page.reload', { ignoreCache: true })
    await waitFor(`localStorage.getItem('${sessionKey}') !== null && localStorage.getItem('${modelKey}') !== 'removed-model'`)
    const after = await evaluate(`localStorage.getItem('${sessionKey}')`)
    const model = await evaluate(`localStorage.getItem('${modelKey}')`)
    if (!uuid.test(after) || before === after) throw new Error('Cleared storage did not generate a new UUID')
    console.log(JSON.stringify({ clearedStorageRecovered: true, removedModelFellBack: true, model }))
  } else {
  const first = await evaluate(`localStorage.getItem('${sessionKey}')`)
  if (!uuid.test(first)) throw new Error('First session is not a UUID')
  const models = (await (await fetch('http://127.0.0.1:8000/models')).json()).models
  const selectedModel = models.at(-1)
  const selected = selectedModel.model_id
  const selectedLabel = selectedModel.provider === 'openrouter' ? 'OpenRouter Free' : 'DeepSeek'
  await evaluate("document.querySelector('button[aria-label=\"Chat model\"]').click()")
  await waitFor("document.querySelector('[data-slot=\"popover-content\"][data-state=\"open\"]')")
  await evaluate(`Array.from(document.querySelectorAll('[data-slot="popover-content"] button')).find(b => b.textContent.trim() === ${JSON.stringify(selectedLabel)}).click()`)
  await waitFor(`localStorage.getItem('${modelKey}') === ${JSON.stringify(selected)}`)
  await call('Page.reload', { ignoreCache: true })
  await waitFor(`document.querySelector('button[aria-label="Chat model"]')?.textContent.includes(${JSON.stringify(selectedLabel)})`)
  if (await evaluate(`localStorage.getItem('${sessionKey}')`) !== first) throw new Error('Session changed on reload')
  const marker = `Persistence smoke ${Date.now()}`
  await evaluate(`(() => { const el = document.querySelector('textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, ${JSON.stringify(marker)}); el.dispatchEvent(new Event('input', {bubbles:true})); return true })()`)
  await evaluate("Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === 'Send').click()")
  await waitFor(`document.body.innerText.includes(${JSON.stringify(marker)})`)
  const historyUrl = `http://127.0.0.1:8000/sessions/${first}/messages`
  const deadline = Date.now() + 90000
  let history = []
  while (Date.now() < deadline) {
    history = await (await fetch(historyUrl)).json()
    if (history.some(m => m.role === 'user' && m.content === marker) && history.some(m => m.role === 'assistant' && m.content)) break
    await new Promise(resolve => setTimeout(resolve, 750))
  }
  if (!history.some(m => m.role === 'assistant' && m.content)) throw new Error('Chat was not persisted')
  await call('Page.reload', { ignoreCache: true })
  await waitFor(`document.body.innerText.includes(${JSON.stringify(marker)})`)
  if (await evaluate(`localStorage.getItem('${sessionKey}')`) !== first) throw new Error('Session changed after history reload')
  await evaluate("Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('New Chat')).click()")
  await waitFor(`localStorage.getItem('${sessionKey}') !== ${JSON.stringify(first)}`)
  const second = await evaluate(`localStorage.getItem('${sessionKey}')`)
  if (!uuid.test(second) || await evaluate(`document.body.innerText.includes(${JSON.stringify(marker)})`)) throw new Error('New Chat did not reset the UI')
  if ((await (await fetch(historyUrl)).json()).length !== history.length) throw new Error('New Chat changed old history')
  console.log(JSON.stringify({ first, second, model: selected, savedMessages: history.length, streamingSaved: true, reloadRestored: true, newChatIsolated: true }))
  }
} finally {
  socket.close()
  await fetch(`${endpoint}/json/close/${tab.id}`)
}
