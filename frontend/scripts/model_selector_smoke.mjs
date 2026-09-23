// Run with the local Vite/FastAPI servers and Edge CDP on port 9225.
// No chat requests or database writes are made.
import { writeFile } from 'node:fs/promises'

const browser = 'http://127.0.0.1:9225'
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
async function waitFor(expression, timeout = 10000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (await evaluate(expression)) return
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error(`Timed out: ${expression}`)
}
const trigger = "document.querySelector('button[aria-label=\"Chat model\"]')"
const menu = "document.querySelector('[data-slot=\"popover-content\"][data-state=\"open\"]')"
try {
  await call('Runtime.enable')
  await call('Page.enable')
  await waitFor(`${trigger} && !${trigger}.disabled`)
  if (await evaluate("document.querySelector('main select') !== null")) throw new Error('Native select remains')
  await evaluate(`${trigger}.click()`)
  await waitFor(menu)
  await new Promise(resolve => setTimeout(resolve, 280))
  const appearance = await evaluate(`(() => { const el=${menu}; const style=getComputedStyle(el); const box=el.getBoundingClientRect(); return { background:style.backgroundColor, blur:style.backdropFilter, zIndex:style.zIndex, portaled:!el.closest('main'), visible:box.width>0 && box.height>0 && box.top>=0 && box.bottom<=innerHeight } })()`)
  if (!appearance.portaled || !appearance.visible || !appearance.blur.includes('blur')) throw new Error('Menu appearance or placement failed')
  await call('Input.dispatchMouseEvent', { type: 'mousePressed', x: 1100, y: 180, button: 'left', clickCount: 1 })
  await call('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 1100, y: 180, button: 'left', clickCount: 1 })
  await waitFor(`!${menu}`)
  await evaluate(`${trigger}.click()`)
  await waitFor(menu)
  await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 })
  await call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 })
  await waitFor(`!${menu}`)
  const models = (await (await fetch('http://127.0.0.1:8000/models')).json()).models
  const current = await evaluate("localStorage.getItem('ai_workspace_model_id')")
  const target = models.find(model => model.model_id !== current) ?? models[0]
  const label = target.provider === 'openrouter' ? 'OpenRouter Free' : 'DeepSeek'
  await evaluate(`${trigger}.click()`)
  await waitFor(menu)
  await evaluate(`Array.from(${menu}.querySelectorAll('button')).find(button => button.textContent.trim() === ${JSON.stringify(label)}).click()`)
  await waitFor(`localStorage.getItem('ai_workspace_model_id') === ${JSON.stringify(target.model_id)} && ${trigger}.textContent.includes(${JSON.stringify(label)})`)
  await waitFor(`!${menu}`)
  await evaluate(`${trigger}.click()`)
  await waitFor(menu)
  await new Promise(resolve => setTimeout(resolve, 280))
  const screenshot = await call('Page.captureScreenshot', { format: 'png' })
  await writeFile('C:/Users/Chenm/AppData/Local/Temp/ai-chat-model-selector.png', Buffer.from(screenshot.data, 'base64'))
  const existing = (await (await fetch('http://127.0.0.1:8000/sessions')).json())[0]
  await evaluate(`localStorage.setItem('ai_workspace_session_id', ${JSON.stringify(existing.session_id)})`)
  await call('Page.reload', { ignoreCache: true })
  await waitFor(`document.querySelector('main')?.innerText.includes(${JSON.stringify(existing.title.slice(0, 16))}) && ${trigger} && !${trigger}.disabled`)
  if (await evaluate("document.querySelector('main select') !== null")) throw new Error('Native select remains in active chat')
  await evaluate(`${trigger}.click()`)
  await waitFor(menu)
  console.log(JSON.stringify({ nativeSelectRemoved: true, activeChatSelector: true, outsideClickCloses: true, escapeCloses: true, selectedModel: target.model_id, menuPortaled: appearance.portaled, menuVisible: appearance.visible, backdropBlur: appearance.blur }))
} finally {
  socket.close()
  await fetch(`${browser}/json/close/${tab.id}`)
}
