// Run with local Vite/FastAPI servers and Edge CDP on port 9225.
// This writes two small test conversations to the configured business database.
const browser = 'http://127.0.0.1:9225'
const backend = 'http://127.0.0.1:8000'
const before = await (await fetch(`${backend}/sessions`)).json()
const tab = await (await fetch(`${browser}/json/new?http://127.0.0.1:5173/chat`, { method: 'PUT' })).json()
const socket = new WebSocket(tab.webSocketDebuggerUrl)
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject })
let nextId = 0
const pending = new Map()
socket.onmessage = ({ data }) => {
  const message = JSON.parse(data)
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
async function waitFor(expression, timeout = 90000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (await evaluate(expression)) return
    await new Promise(resolve => setTimeout(resolve, 200))
  }
  throw new Error(`Timed out: ${expression}`)
}
async function send(marker) {
  await evaluate(`(() => { const el = document.querySelector('textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, ${JSON.stringify(marker)}); el.dispatchEvent(new Event('input', {bubbles:true})); return true })()`)
  await evaluate("Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === 'Send').click()")
  const session = await evaluate("localStorage.getItem('ai_workspace_session_id')")
  await waitFor(`document.querySelector('main')?.innerText.includes(${JSON.stringify(marker)})`)
  const url = `${backend}/sessions/${session}/messages`
  const deadline = Date.now() + 90000
  while (Date.now() < deadline) {
    const messages = await (await fetch(url)).json()
    if (messages.length === 2 && messages[0].content === marker && messages[1].content) return session
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  throw new Error(`Chat did not persist for ${session}`)
}
try {
  await call('Runtime.enable')
  await call('Page.enable')
  await waitFor("document.querySelector('button[aria-label=\"Chat model\"]:not(:disabled)') && document.body.innerText.includes('历史记录')")
  const models = (await (await fetch(`${backend}/models`)).json()).models
  const model = models.find(item => item.model_id === 'openrouter/free') ?? models[0]
  const modelLabel = model.provider === 'openrouter' ? 'OpenRouter Free' : 'DeepSeek'
  await evaluate("document.querySelector('button[aria-label=\"Chat model\"]').click()")
  await waitFor("document.querySelector('[data-slot=\"popover-content\"][data-state=\"open\"]')")
  await evaluate(`Array.from(document.querySelectorAll('[data-slot="popover-content"] button')).find(b => b.textContent.trim() === ${JSON.stringify(modelLabel)}).click()`)
  await waitFor("!Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('New Chat'))?.disabled")
  await evaluate("Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('New Chat')).click()")
  const stamp = Date.now()
  const titleA = `History A ${stamp}`
  const titleB = `History B ${stamp}`
  const sessionA = await send(titleA)
  await waitFor(`Array.from(document.querySelectorAll('button[title]')).some(b => b.title === ${JSON.stringify(titleA)})`)
  await evaluate("Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('New Chat')).click()")
  await waitFor(`localStorage.getItem('ai_workspace_session_id') !== ${JSON.stringify(sessionA)}`)
  const sessionB = await send(titleB)
  if (sessionA === sessionB) throw new Error('New Chat reused the old session')
  await waitFor(`Array.from(document.querySelectorAll('button[title]')).some(b => b.title === ${JSON.stringify(titleB)})`)
  await evaluate(`Array.from(document.querySelectorAll('button[title]')).find(b => b.title === ${JSON.stringify(titleA)}).click()`)
  await waitFor(`localStorage.getItem('ai_workspace_session_id') === ${JSON.stringify(sessionA)} && document.querySelector('main')?.innerText.includes(${JSON.stringify(titleA)})`)
  if (!await evaluate(`Array.from(document.querySelectorAll('button[title]')).find(b => b.title === ${JSON.stringify(titleA)})?.parentElement.className.includes('bg-sidebar-accent')`)) throw new Error('A is not highlighted')
  if (await evaluate(`document.querySelector('main')?.innerText.includes(${JSON.stringify(titleB)})`)) throw new Error('B leaked into A')
  await evaluate(`Array.from(document.querySelectorAll('button[title]')).find(b => b.title === ${JSON.stringify(titleB)}).click()`)
  await waitFor(`localStorage.getItem('ai_workspace_session_id') === ${JSON.stringify(sessionB)} && document.querySelector('main')?.innerText.includes(${JSON.stringify(titleB)})`)
  if (!await evaluate(`Array.from(document.querySelectorAll('button[title]')).find(b => b.title === ${JSON.stringify(titleB)})?.parentElement.className.includes('bg-sidebar-accent')`)) throw new Error('B is not highlighted')
  if (await evaluate(`document.querySelector('main')?.innerText.includes(${JSON.stringify(titleA)})`)) throw new Error('A leaked into B')
  await call('Page.reload', { ignoreCache: true })
  await waitFor(`localStorage.getItem('ai_workspace_session_id') === ${JSON.stringify(sessionB)} && document.querySelector('main')?.innerText.includes(${JSON.stringify(titleB)})`)
  await evaluate("Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('New Chat')).click()")
  await waitFor(`localStorage.getItem('ai_workspace_session_id') !== ${JSON.stringify(sessionB)}`)
  if (await evaluate(`document.querySelector('main')?.innerText.includes(${JSON.stringify(titleB)})`)) throw new Error('New Chat did not clear the displayed conversation')
  await evaluate(`Array.from(document.querySelectorAll('button[title]')).find(b => b.title === ${JSON.stringify(titleA)}).click()`)
  await waitFor(`localStorage.getItem('ai_workspace_session_id') === ${JSON.stringify(sessionA)} && document.querySelector('main')?.innerText.includes(${JSON.stringify(titleA)}) && !Array.from(document.querySelectorAll('button[aria-label]')).find(b => b.getAttribute('aria-label') === ${JSON.stringify(`会话操作：${titleA}`)})?.disabled`)
  await evaluate(`(() => { window.confirm = () => true; Array.from(document.querySelectorAll('button[aria-label]')).find(b => b.getAttribute('aria-label') === ${JSON.stringify(`会话操作：${titleA}`)}).click(); return true })()`)
  await waitFor("Array.from(document.querySelectorAll('button')).some(b => b.textContent.trim() === '删除')")
  await evaluate("Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === '删除').click()")
  await waitFor(`localStorage.getItem('ai_workspace_session_id') !== ${JSON.stringify(sessionA)} && !Array.from(document.querySelectorAll('button[title]')).some(b => b.title === ${JSON.stringify(titleA)})`)
  const newSession = await evaluate("localStorage.getItem('ai_workspace_session_id')")
  if (newSession === sessionB || await evaluate(`document.querySelector('main')?.innerText.includes(${JSON.stringify(titleA)})`)) throw new Error('Deleting the selected session did not start a new chat')
  const after = await (await fetch(`${backend}/sessions`)).json()
  if (after.some(item => item.session_id === sessionA) || !after.some(item => item.session_id === sessionB)) throw new Error('Delete removed the wrong session')
  if (!before.every(item => after.some(next => next.session_id === item.session_id))) throw new Error('An old session disappeared')
  if ((await (await fetch(`${backend}/sessions/${sessionA}/messages`)).json()).length !== 0) throw new Error('A still has messages')
  if ((await (await fetch(`${backend}/sessions/${sessionB}/messages`)).json()).length !== 2) throw new Error('B messages changed')
  console.log(JSON.stringify({ before: before.length, after: after.length, deletedSession: sessionA, retainedSession: sessionB, model: model.model_id, clickA: true, clickB: true, reloadB: true, newChat: true, deletedCurrent: true }))
} finally {
  socket.close()
  await fetch(`${browser}/json/close/${tab.id}`)
}
