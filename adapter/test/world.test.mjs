import { test } from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { Vec3 } from 'vec3'
import { MineflayerWorld } from '../world.mjs'

// Ground at y 63 and air above it, except the cells listed as "x,y,z": boundingBox. Holds one crafting table.
function placingBot (position, cells) {
  const placed = []
  let items = [{ name: 'crafting_table', count: 1 }]
  return Object.assign(new EventEmitter(), {
    placed,
    entity: { position },
    inventory: { items: () => items },
    blockAt: at => ({ position: at, boundingBox: cells[`${at.x},${at.y},${at.z}`] ?? (at.y < 64 ? 'block' : 'empty') }),
    equip: async () => {},
    placeBlock: async (reference, face) => {
      placed.push([reference.position, face])
      items = []
    }
  })
}

test('inventory counts wood variants under generic names', () => {
  const items = [{ name: 'oak_log', count: 2 }, { name: 'birch_log', count: 1 }, { name: 'oak_planks', count: 4 }, { name: 'stick', count: 3 }]
  const world = new MineflayerWorld({ inventory: { items: () => items } }, 'test')
  assert.deepEqual(world.inventory(), { log: 3, planks: 4, stick: 3 })
})

test('a step that outlasts its bound returns ok false and stops the pathfinder', async () => {
  const bot = Object.assign(new EventEmitter(), {
    entity: { position: new Vec3(0.5, 64, 0.5) },
    currentWindow: null,
    stopDigging () {},
    pathfinder: { goto: () => new Promise(() => {}), setGoal (goal) { this.goal = goal } }
  })
  const result = await new MineflayerWorld(bot, 'test', 20).act({ action: 'move', target: 'north' })
  assert.deepEqual(
    { result, goal: bot.pathfinder.goal },
    { result: { ok: false, message: 'move: step timed out after 0.02 s', output: null, events: [] }, goal: null }
  )
})

test('place uses the first free cell on solid ground that the bot does not overlap', async () => {
  // North holds a block, south has no ground under it, the bot leans 0.4 into east, west fits.
  const bot = placingBot(new Vec3(0.9, 64, 0.5), { '0,64,-1': 'block', '0,63,1': 'empty' })
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'place', target: 'crafting_table' })
  assert.deepEqual(
    { result, placed: bot.placed },
    {
      result: { ok: true, message: 'placed crafting_table at -1,64,0', output: { crafting_table: -1 }, events: [] },
      placed: [[new Vec3(-1, 63, 0), new Vec3(0, 1, 0)]]
    }
  )
})

test('place without a free cell on solid ground fails with a message', async () => {
  const walls = { '0,64,-1': 'block', '0,64,1': 'block', '1,64,0': 'block', '-1,64,0': 'block' }
  const world = new MineflayerWorld(placingBot(new Vec3(0.5, 64, 0.5), walls), 'test')
  const result = await world.act({ action: 'place', target: 'crafting_table' })
  assert.deepEqual(result, { ok: false, message: 'place: no adjacent solid spot for crafting_table', output: null, events: [] })
})
