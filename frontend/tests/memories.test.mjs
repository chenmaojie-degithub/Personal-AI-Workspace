import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope, ref } from 'vue'
import { useMemories } from '../src/lib/memories.ts'

const row = (workspace = 'a', version = 1) => ({ id: 'memory', workspace_id: workspace,
  key: 'language', value: '中文', version, created_at: '2026-10-21T00:00:00Z', updated_at: '2026-10-21T00:00:00Z' })
const response = (data, status = 200) => new Response(status === 204 ? null : JSON.stringify(data), { status })
const tick = () => new Promise(resolve => setImmediate(resolve))
function deferred() { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
function manager(t, fetch) {
  const original = globalThis.fetch
  globalThis.fetch = fetch
  const scope = effectScope(), workspace = ref('a')
  const state = scope.run(() => useMemories(workspace))
  t.after(() => { scope.stop(); globalThis.fetch = original })
  return { state, workspace, scope }
}

test('loads rows and sends confirmed CRUD with expected_version; no localStorage', async t => {
  const storage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new Error('Memory must not access localStorage') } })
  t.after(() => { if (storage) Object.defineProperty(globalThis, 'localStorage', storage); else delete globalThis.localStorage })
  const requests = []
  const { state } = manager(t, async (url, init = {}) => {
    requests.push({ url, ...init })
    return init.method ? response({}, init.method === 'DELETE' ? 204 : 200) : response([row()])
  })
  await tick()
  assert.equal(state.rows.value[0].value, '中文')
  assert.equal(await state.create('key', 'value', false), false)
  assert.equal(await state.remove(row(), false), false)
  assert.equal(requests.length, 1)
  await state.create('key', 'value', true)
  await state.update(row(), 'English', true)
  await state.remove(row(), true)
  const writes = requests.filter(request => request.method)
  assert.deepEqual(JSON.parse(writes[0].body), { key: 'key', value: 'value', confirmed: true })
  assert.deepEqual(JSON.parse(writes[1].body), { value: 'English', expected_version: 1, confirmed: true })
  assert.match(writes[2].url, /expected_version=1$/)
})

test('late A GET cannot replace B; switching back and refresh reloads server state', async t => {
  const late = deferred()
  let first = true
  const { state, workspace } = manager(t, async url => {
    if (first) { first = false; return late.promise }
    return response([row(url.includes('/b/') ? 'b' : 'a', 2)])
  })
  workspace.value = 'b'
  await tick()
  late.resolve(response([row('a')]))
  await tick()
  assert.equal(state.rows.value[0].workspace_id, 'b')
  workspace.value = 'a'
  await tick()
  assert.equal(state.rows.value[0].version, 2)
  await state.reload()
  assert.equal(state.rows.value[0].workspace_id, 'a')
})

test('out of order reload, including body parsing, cannot replace newer response', async t => {
  const slowBody = deferred()
  let count = 0
  const { state } = manager(t, async () => ++count === 1
    ? { ok: true, json: () => slowBody.promise }
    : response([row('a', 3)]))
  await tick()
  await state.reload()
  slowBody.resolve([row('a', 1)])
  await tick()
  assert.equal(state.rows.value[0].version, 3)
})

test('409 reloads newest version without automatic overwrite or retry', async t => {
  const calls = []
  const { state } = manager(t, async (_, init = {}) => {
    calls.push(init.method || 'GET')
    return init.method ? response({}, 409) : response([row('a', calls.length > 1 ? 2 : 1)])
  })
  await tick()
  assert.equal(await state.update(row(), 'draft', true), false)
  assert.match(state.error.value, /409|冲突/)
  assert.equal(state.rows.value[0].version, 2)
  assert.deepEqual(calls, ['GET', 'PATCH', 'GET'])
})

test('503 disables mutations; explicit refresh can recover', async t => {
  let enabled = false, calls = 0
  const { state } = manager(t, async () => { calls++; return enabled ? response([row()]) : response({}, 503) })
  await tick()
  assert.equal(state.unavailable.value, true)
  assert.match(state.error.value, /未启用/)
  assert.equal(await state.create('k', 'v', true), false)
  assert.equal(calls, 1)
  enabled = true
  await state.reload()
  assert.equal(state.unavailable.value, false)
})

test('duplicate submit blocked; late mutation failure cannot leak into new Workspace', async t => {
  const write = deferred()
  let writes = 0
  const { state, workspace } = manager(t, async (url, init = {}) => {
    if (init.method) { writes++; return write.promise }
    return response([row(url.includes('/b/') ? 'b' : 'a')])
  })
  await tick()
  const pending = state.update(row(), 'pending', true)
  assert.equal(await state.update(row(), 'again', true), false)
  workspace.value = 'b'
  await tick()
  write.resolve(response({}, 503))
  assert.equal(await pending, false)
  assert.equal(state.rows.value[0].workspace_id, 'b')
  assert.equal(state.unavailable.value, false)
  assert.equal(state.saving.value, false)
  assert.equal(state.error.value, '')
  assert.equal(writes, 1)
})

test('network failure is actionable; disposed or aborted callbacks cannot change state', async t => {
  let fail = false
  const { state, scope } = manager(t, async () => {
    if (fail) throw new Error('synthetic network failure')
    return response([row()])
  })
  await tick()
  fail = true
  assert.equal(await state.create('k', 'v', true), false)
  assert.match(state.error.value, /结果未知/)
  scope.stop()
  assert.equal(state.rows.value.length, 0)
})

test('orphan preview is metadata-only and scope guarded', async t => {
  const pending = deferred()
  const { state, workspace } = manager(t, async url => url.endsWith('/orphans') ? pending.promise : response([]))
  await tick()
  const inspect = state.inspectOrphans()
  workspace.value = 'b'
  pending.resolve(response({ orphans: [{ workspace_id: 'gone', count: 2 }], record_count: 2, action: 'retain', atomic_snapshot: false }))
  await inspect
  assert.equal(state.preview.value, null)
})

test('A to B to A does not accept an old successful mutation', async t => {
  const late = deferred()
  const { state, workspace } = manager(t, async (url, init = {}) => init.method
    ? late.promise : response([row(url.includes('/b/') ? 'b' : 'a', 4)]))
  await tick()
  const pending = state.create('old', 'old draft', true)
  workspace.value = 'b'
  workspace.value = 'a'
  await tick()
  late.resolve(response({}))
  assert.equal(await pending, false)
  assert.equal(state.rows.value[0].version, 4)
  assert.equal(state.saving.value, false)
})

test('unmount ignores a delayed list response and 404 clears stale rows', async t => {
  const late = deferred()
  let count = 0
  const { state, scope } = manager(t, async () => {
    count++
    if (count === 1) return response([row()])
    if (count === 2) return response({}, 404)
    return late.promise
  })
  await tick()
  await state.reload()
  assert.equal(state.rows.value.length, 0)
  assert.match(state.error.value, /不存在/)
  const pending = state.reload()
  scope.stop()
  late.resolve(response([row()]))
  await pending
  assert.equal(state.rows.value.length, 0)
})
