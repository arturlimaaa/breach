import { test } from 'node:test'
import assert from 'node:assert/strict'
import { once } from 'node:events'
import { FakeWorld } from '../fake.mjs'
import { serve } from '../server.mjs'

const BLOCKS = [{ x: 1, y: 64, z: 0, block: 'log' }, { x: 2, y: 64, z: 0, block: 'log' }, { x: 0, y: 63, z: 3, block: 'stone' }]

async function start (t) {
  const server = serve(new FakeWorld(BLOCKS)).listen(0, '127.0.0.1')
  await once(server, 'listening')
  t.after(() => server.close())
  const base = `http://127.0.0.1:${server.address().port}`
  return async (method, path, body) => {
    const response = await fetch(base + path, { method, body: body && JSON.stringify(body) })
    return { status: response.status, body: await response.json() }
  }
}

const task = (fields) => ({ task: { task_id: 't', goal: 'log', count: 2, budget: 3, inventory: { planks: 4 }, ...fields } })

test('reset returns the observation of the task start', async (t) => {
  const call = await start(t)
  const { body } = await call('POST', '/reset', task())
  assert.deepEqual(body, {
    server: 'fake/flat',
    position: { x: 0, y: 64, z: 0 },
    inventory: { planks: 4 },
    visible: BLOCKS,
    action_count: 0,
    budget: 3,
    done: false,
    success: false
  })
})

test('a step returns its result, events, and the next observation', async (t) => {
  const call = await start(t)
  await call('POST', '/reset', task())
  const { body } = await call('POST', '/step', { action: 'mine', target: 'log' })
  assert.deepEqual(body, {
    ok: true,
    message: 'mined log',
    output: { block_removed: true, collected: { log: 1 } },
    events: [],
    observation: {
      server: 'fake/flat',
      position: { x: 0, y: 64, z: 0 },
      inventory: { planks: 4, log: 1 },
      visible: BLOCKS.slice(1),
      action_count: 1,
      budget: 3,
      done: false,
      success: false
    }
  })
})

test('observe repeats the observation without counting an action', async (t) => {
  const call = await start(t)
  const reset = await call('POST', '/reset', task())
  const observed = await call('GET', '/observe')
  assert.deepEqual(observed.body, reset.body)
})

test('holding the goal count ends the episode with success', async (t) => {
  const call = await start(t)
  await call('POST', '/reset', task())
  await call('POST', '/step', { action: 'mine', target: 'log' })
  const { body: { observation: { action_count, done, success } } } = await call('POST', '/step', { action: 'mine', target: 'log' })
  assert.deepEqual({ action_count, done, success }, { action_count: 2, done: true, success: true })
})

test('the budget ends the episode and later steps are refused without counting', async (t) => {
  const call = await start(t)
  await call('POST', '/reset', task({ budget: 1 }))
  await call('POST', '/step', { action: 'look' })
  const { body: { observation, ...result } } = await call('POST', '/step', { action: 'mine', target: 'log' })
  assert.deepEqual(
    { result, action_count: observation.action_count, done: observation.done },
    { result: { ok: false, message: 'episode is over', output: null, events: [] }, action_count: 1, done: true }
  )
})

test('early, malformed, and unknown requests are refused with a status', async (t) => {
  const call = await start(t)
  const early = await call('GET', '/observe')
  await call('POST', '/reset', task())
  const statuses = [early.status, (await call('POST', '/step', { target: 'log' })).status, (await call('GET', '/nowhere')).status]
  assert.deepEqual(statuses, [409, 400, 404])
})
