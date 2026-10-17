import { test } from 'node:test'
import assert from 'node:assert/strict'
import { once } from 'node:events'
import { FakeWorld } from '../fake.mjs'
import { serve } from '../server.mjs'

const BLOCKS = [{ x: 1, y: 64, z: 0, block: 'log' }, { x: 2, y: 64, z: 0, block: 'log' }, { x: 0, y: 63, z: 3, block: 'stone' }]

async function start (t, log = () => {}) {
  const server = serve(new FakeWorld(BLOCKS), log).listen(0, '127.0.0.1')
  await once(server, 'listening')
  t.after(() => server.close())
  const base = `http://127.0.0.1:${server.address().port}`
  return async (method, path, body) => {
    const response = await fetch(base + path, { method, body: body && JSON.stringify(body) })
    return { status: response.status, body: await response.json() }
  }
}

const task = (fields) => ({ task: { task_id: 't', goal: 'log', count: 2, budget: 3, inventory: { planks: 4 }, ...fields } })

test('each reset and step prints one log line with its time, action, target, ok, message, and output', async (t) => {
  const lines = []
  const call = await start(t, line => lines.push(JSON.parse(line)))
  await call('POST', '/reset', task())
  await call('POST', '/step', { action: 'mine', target: 'log' })
  await call('GET', '/observe')
  assert.deepEqual(lines.map(({ time, ...line }) => ({ time: !Number.isNaN(Date.parse(time)), ...line })), [
    {
      time: true,
      action: 'reset',
      target: { task_id: 't', goal: 'log', count: 2, budget: 3, inventory: { planks: 4 } },
      ok: true,
      message: '/clear; /give @s planks 4',
      output: null,
      at: { x: 0, y: 64, z: 0 }
    },
    {
      time: true,
      action: 'mine',
      target: 'log',
      ok: true,
      message: 'mined log',
      output: { block_removed: true, collected: { log: 1 } },
      executed: true,
      at: { x: 0, y: 64, z: 0 }
    }
  ])
})

test('reset returns the observation of the task start and the commands that set it up', async (t) => {
  const call = await start(t)
  const { body } = await call('POST', '/reset', task())
  assert.deepEqual(body, {
    message: '/clear; /give @s planks 4',
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
    executed: true,
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

test('look reports the nearest known block per heading and leaves empty headings out', async (t) => {
  const call = await start(t)
  await call('POST', '/reset', task())
  const { body: { observation, ...result } } = await call('POST', '/step', { action: 'look' })
  assert.deepEqual(result, {
    ok: true,
    message: 'blocks along 4 headings',
    output: {
      E: { block: 'log', distance: 1 },
      SE: { block: 'stone', distance: 3 },
      S: { block: 'stone', distance: 3 },
      SW: { block: 'stone', distance: 3 }
    },
    events: [],
    executed: true
  })
})

test('observe repeats the observation without counting an action', async (t) => {
  const call = await start(t)
  const { body: { message, ...observation } } = await call('POST', '/reset', task())
  const observed = await call('GET', '/observe')
  assert.deepEqual(observed.body, observation)
})

test('holding the goal count ends the episode with success', async (t) => {
  const call = await start(t)
  await call('POST', '/reset', task())
  await call('POST', '/step', { action: 'mine', target: 'log' })
  const { body: { observation: { action_count, done, success } } } = await call('POST', '/step', { action: 'mine', target: 'log' })
  assert.deepEqual({ action_count, done, success }, { action_count: 2, done: true, success: true })
})

test('steps after success still run until the budget is spent', async (t) => {
  const call = await start(t)
  await call('POST', '/reset', task({ count: 1, budget: 3 }))
  await call('POST', '/step', { action: 'mine', target: 'log' })
  const { body: { observation, ...result } } = await call('POST', '/step', { action: 'mine', target: 'log' })
  assert.deepEqual(
    { result, action_count: observation.action_count, done: observation.done, success: observation.success },
    {
      result: { ok: true, message: 'mined log', output: { block_removed: true, collected: { log: 1 } }, events: [], executed: true },
      action_count: 2,
      done: true,
      success: true
    }
  )
})

test('a step the world refuses reports executed false', async (t) => {
  const call = await start(t)
  await call('POST', '/reset', task())
  const { body: { observation, ...result } } = await call('POST', '/step', { action: 'craft', target: 'stick' })
  assert.deepEqual(result, { ok: false, message: 'fake world cannot craft stick', output: null, events: [], executed: false })
})

test('the budget ends the episode and later steps are refused without counting', async (t) => {
  const call = await start(t)
  await call('POST', '/reset', task({ budget: 1 }))
  await call('POST', '/step', { action: 'look' })
  const { body: { observation, ...result } } = await call('POST', '/step', { action: 'mine', target: 'log' })
  assert.deepEqual(
    { result, action_count: observation.action_count, done: observation.done },
    { result: { ok: false, message: 'episode is over', output: null, events: [], executed: false }, action_count: 1, done: true }
  )
})

test('early, malformed, and unknown requests are refused with a status', async (t) => {
  const call = await start(t)
  const early = await call('GET', '/observe')
  await call('POST', '/reset', task())
  const statuses = [early.status, (await call('POST', '/step', { target: 'log' })).status, (await call('GET', '/nowhere')).status]
  assert.deepEqual(statuses, [409, 400, 404])
})
