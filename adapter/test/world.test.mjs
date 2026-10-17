import { test } from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import pathfinderPlugin from 'mineflayer-pathfinder'
import { Vec3 } from 'vec3'
import { MineflayerWorld } from '../world.mjs'

const { goals } = pathfinderPlugin

// One log at `log`, the bot at `feet`. Digging drops the log at `drop`, which the bot picks up only by standing in
// the drop's cell, as when it rolls out of pickup range. Only a GoalBlock moves the bot. When the drop is not
// reachable, the pathfinder keeps its goal and rejects, as the real one does on a partial path.
function miningBot (feet, log, drop, reachable = true) {
  let standing = true
  let items = []
  const bot = Object.assign(new EventEmitter(), {
    goals: [],
    entity: { position: feet },
    entities: {},
    inventory: { items: () => items },
    findBlocks: () => standing ? [log] : [],
    blockAt: at => ({ name: standing && at.equals(log) ? 'oak_log' : 'air', position: at }),
    canSeeBlock: () => true,
    equip: async () => {},
    dig: async () => {
      standing = false
      bot.entities[1] = { name: 'item', position: drop }
    },
    pathfinder: {
      bestHarvestTool: () => null,
      setGoal (goal) { this.goal = goal },
      async goto (goal) {
        bot.goals.push(goal.constructor.name)
        if (!(goal instanceof goals.GoalBlock)) return
        if (!reachable) {
          this.goal = goal
          throw Object.assign(new Error('No path to the goal!'), { name: 'NoPath' })
        }
        bot.entity.position = new Vec3(goal.x + 0.5, goal.y, goal.z + 0.5)
        if (bot.entity.position.floored().equals(drop.floored())) items = [{ name: 'oak_log', count: 1 }]
      }
    }
  })
  return bot
}

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
    { result: { ok: false, message: 'move: step timed out after 0.02 s', output: null, events: [], executed: false }, goal: null }
  )
})

test('place uses the first free cell on solid ground that the bot does not overlap', async () => {
  // North holds a block, south has no ground under it, the bot leans 0.4 into east, west fits.
  const bot = placingBot(new Vec3(0.9, 64, 0.5), { '0,64,-1': 'block', '0,63,1': 'empty' })
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'place', target: 'crafting_table' })
  assert.deepEqual(
    { result, placed: bot.placed },
    {
      result: { ok: true, message: 'placed crafting_table at -1,64,0', output: { crafting_table: -1 }, events: [], executed: true },
      placed: [[new Vec3(-1, 63, 0), new Vec3(0, 1, 0)]]
    }
  )
})

test('place without a free cell on solid ground fails with a message', async () => {
  const walls = { '0,64,-1': 'block', '0,64,1': 'block', '1,64,0': 'block', '-1,64,0': 'block' }
  const world = new MineflayerWorld(placingBot(new Vec3(0.5, 64, 0.5), walls), 'test')
  const result = await world.act({ action: 'place', target: 'crafting_table' })
  assert.deepEqual(result, { ok: false, message: 'place: no adjacent solid spot for crafting_table', output: null, events: [], executed: false })
})

test('mine walks onto a drop that rolled out of pickup range', async () => {
  const bot = miningBot(new Vec3(0.5, 64, 0.5), new Vec3(1, 64, 0), new Vec3(2.6, 64, 0.4))
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'mine', target: 'log' })
  assert.deepEqual(
    { result, goals: bot.goals },
    {
      result: { ok: true, message: 'mined log', output: { block_removed: true, collected: { log: 1 } }, events: [], executed: true },
      goals: ['GoalCompositeAll', 'GoalBlock']
    }
  )
})

test('mine reaches a log four blocks above the feet', async () => {
  const bot = miningBot(new Vec3(0.5, 64, 0.5), new Vec3(0, 68, 0), new Vec3(0.5, 64, 0.5))
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'mine', target: 'log' })
  assert.deepEqual(result, { ok: true, message: 'mined log', output: { block_removed: true, collected: { log: 1 } }, events: [], executed: true })
})

test('a move with no path stops the pathfinder, which would otherwise keep walking its partial path', async () => {
  const noPath = Object.assign(new Error('No path to the goal!'), { name: 'NoPath' })
  const bot = Object.assign(new EventEmitter(), {
    entity: { position: new Vec3(0.5, 64, 0.5) },
    pathfinder: {
      goto (goal) {
        this.goal = goal
        return Promise.reject(noPath)
      },
      setGoal (goal) { this.goal = goal }
    }
  })
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'move', target: 'north' })
  assert.deepEqual(
    { result, goal: bot.pathfinder.goal },
    { result: { ok: false, message: 'move: No path to the goal!', output: null, events: [], executed: false }, goal: null }
  )
})

test('mine stops the pathfinder when the drop has no path', async () => {
  const bot = miningBot(new Vec3(0.5, 64, 0.5), new Vec3(1, 64, 0), new Vec3(2.6, 64, 0.4), false)
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'mine', target: 'log' })
  assert.deepEqual(
    { result, goal: bot.pathfinder.goal },
    { result: { ok: true, message: 'mined log', output: { block_removed: true, collected: {} }, events: [], executed: true }, goal: null }
  )
})

test('an unknown action is refused without executing', async () => {
  const result = await new MineflayerWorld(new EventEmitter(), 'test').act({ action: 'fly' })
  assert.deepEqual(result, { ok: false, message: 'fly: unknown action', output: null, events: [], executed: false })
})

test('a mine whose walk to the block fails is refused without executing', async () => {
  const bot = miningBot(new Vec3(0.5, 64, 0.5), new Vec3(5, 64, 0), new Vec3(5.5, 64, 0.5))
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'mine', target: 'log' })
  assert.deepEqual(result, { ok: false, message: 'mine: no path to log', output: null, events: [], executed: false })
})
