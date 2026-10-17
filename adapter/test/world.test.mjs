import { test } from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { Vec3 } from 'vec3'
import { MineflayerWorld } from '../world.mjs'

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
