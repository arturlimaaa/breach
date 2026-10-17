import { test } from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import minecraftData from 'minecraft-data'
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

// Logs in sight at `logs`, nearest first, and the bot at `feet`. A path to a log in `blocked` fails as the pathfinder
// does on a partial path; any other path ends in the column east of its log. Digging a log collects it.
function forestBot (feet, logs, blocked = []) {
  const standing = new Set(logs.map(String))
  let items = []
  const bot = Object.assign(new EventEmitter(), {
    paths: [],
    dug: [],
    entity: { position: feet },
    entities: {},
    inventory: { items: () => items },
    findBlocks: () => logs.filter(log => standing.has(String(log))),
    blockAt: at => ({ name: standing.has(String(at)) ? 'oak_log' : 'air', position: at }),
    canSeeBlock: () => true,
    equip: async () => {},
    dig: async block => {
      standing.delete(String(block.position))
      bot.dug.push(block.position)
      items = [{ name: 'oak_log', count: bot.dug.length }]
    },
    pathfinder: {
      setGoal () {},
      async goto (goal) {
        const [{ x, z }] = goal.goals
        bot.paths.push([x, z])
        if (blocked.some(log => log.x === x && log.z === z)) throw Object.assign(new Error('No path to the goal!'), { name: 'NoPath' })
        bot.entity.position = new Vec3(x + 1.5, feet.y, z + 0.5)
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
      goals: ['GoalBlock']
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

test('a toward-move diagonally next to the nearest block, one below it, is ok without a path', async () => {
  const log = new Vec3(60, 71, -109)
  const bot = forestBot(new Vec3(59.5, 70, -109.5), [log], [log])
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'move', target: { toward: 'log' } })
  assert.deepEqual(
    { result, paths: bot.paths },
    { result: { ok: true, message: 'moved toward log', output: null, events: [], executed: true }, paths: [] }
  )
})

test('a toward-move whose nearest block has no path walks to the next nearest', async () => {
  const [a, b, c] = [new Vec3(5, 65, 0), new Vec3(0, 65, 6), new Vec3(-7, 65, 0)]
  const bot = forestBot(new Vec3(0.5, 64, 0.5), [a, b, c], [a])
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'move', target: { toward: 'log' } })
  assert.deepEqual(
    { result, paths: bot.paths },
    { result: { ok: true, message: 'moved toward log', output: null, events: [], executed: true }, paths: [[5, 0], [0, 6]] }
  )
})

test('a toward-move answers no path after the three nearest blocks have none', async () => {
  const logs = [new Vec3(5, 65, 0), new Vec3(0, 65, 6), new Vec3(-7, 65, 0), new Vec3(0, 65, -8)]
  const bot = forestBot(new Vec3(0.5, 64, 0.5), logs, logs)
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'move', target: { toward: 'log' } })
  assert.deepEqual(
    { result, paths: bot.paths },
    {
      result: { ok: false, message: 'move: no path toward log', output: null, events: [], executed: false },
      paths: [[5, 0], [0, 6], [-7, 0]]
    }
  )
})

test('mine digs the nearest block that has a path, the one a toward-move reaches', async () => {
  const [a, b] = [new Vec3(5, 65, 0), new Vec3(0, 65, 6)]
  const bot = forestBot(new Vec3(0.5, 64, 0.5), [a, b], [a])
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'mine', target: 'log' })
  assert.deepEqual(
    { result, dug: bot.dug },
    { result: { ok: true, message: 'mined log', output: { block_removed: true, collected: { log: 1 } }, events: [], executed: true }, dug: [b] }
  )
})

// The bot at `feet`. A path whose goal `reachable` accepts ends in the goal's column; any other path stops one block
// toward its goal and rejects, as the pathfinder's partial paths do.
function walkingBot (feet, reachable) {
  const bot = Object.assign(new EventEmitter(), {
    paths: [],
    entity: { position: feet },
    pathfinder: {
      setGoal () {},
      async goto (goal) {
        bot.paths.push([goal.x, goal.z])
        const at = bot.entity.position.floored()
        if (reachable(goal)) {
          bot.entity.position = new Vec3(goal.x + 0.5, feet.y, goal.z + 0.5)
          return
        }
        bot.entity.position = bot.entity.position.offset(Math.sign(goal.x - at.x), 0, Math.sign(goal.z - at.z))
        throw Object.assign(new Error('No path to the goal!'), { name: 'NoPath' })
      }
    }
  })
  return bot
}

test('a heading move reaches the point n blocks along it, a diagonal block being one on each axis', async () => {
  const bot = walkingBot(new Vec3(0.5, 64, 0.5), () => true)
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'move', target: { heading: 'NE', blocks: 8 } })
  assert.deepEqual(
    { result, paths: bot.paths },
    { result: { ok: true, message: 'moved 8 blocks NE', output: { x: 8, y: 64, z: -8 }, events: [], executed: true }, paths: [[8, -8]] }
  )
})

test('a heading move with no path to its point falls back to half, then a quarter, of the same line', async () => {
  const bot = walkingBot(new Vec3(0.5, 64, 0.5), goal => goal.x <= 5)
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'move', target: { heading: 'E', blocks: 16 } })
  assert.deepEqual(
    { result, paths: bot.paths },
    {
      result: { ok: true, message: 'moved 4 blocks E', output: { x: 4, y: 64, z: 0 }, events: [], executed: true },
      paths: [[16, 0], [8, 0], [4, 0]]
    }
  )
})

test('a blocked heading move fails where its partial paths left the bot, executed', async () => {
  const bot = walkingBot(new Vec3(0.5, 64, 0.5), () => false)
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'move', target: { heading: 'E', blocks: 16 } })
  assert.deepEqual(
    { result, paths: bot.paths },
    {
      result: { ok: false, message: 'no path E', output: { x: 3, y: 64, z: 0 }, events: [], executed: true },
      paths: [[16, 0], [8, 0], [4, 0]]
    }
  )
})

test('a heading move with an unknown heading is refused without executing', async () => {
  const bot = walkingBot(new Vec3(0.5, 64, 0.5), () => true)
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'move', target: { heading: 'UP', blocks: 8 } })
  assert.deepEqual(
    { result, paths: bot.paths },
    {
      result: { ok: false, message: 'move: heading must be N, NE, E, SE, S, SW, W, or NW, and blocks a positive integer', output: null, events: [], executed: false },
      paths: []
    }
  )
})

test('a trunk under leaves one block away is in the observation and minable', async () => {
  // Leaves above and around the trunk, dirt under it: only its face toward the bot touches air, and no ray from the
  // bot's eyes reaches its center.
  const cells = new Map([
    [[1, 64, 0], 'oak_log'], [[1, 65, 0], 'oak_leaves'], [[2, 64, 0], 'oak_leaves'], [[1, 64, 1], 'oak_leaves'],
    [[1, 64, -1], 'oak_leaves'], [[1, 63, 0], 'dirt']
  ].map(([cell, name]) => [String(new Vec3(...cell)), { position: new Vec3(...cell), name }]))
  let items = []
  const bot = Object.assign(new EventEmitter(), {
    entity: { position: new Vec3(0.5, 64, 0.5) },
    entities: {},
    inventory: { items: () => items },
    findBlocks: () => [...cells.values()].map(cell => cell.position),
    blockAt: at => ({ name: cells.get(String(at))?.name ?? 'air', position: at }),
    canSeeBlock: () => false,
    equip: async () => {},
    dig: async block => {
      cells.delete(String(block.position))
      items = [{ name: 'oak_log', count: 1 }]
    },
    pathfinder: { setGoal () {}, goto: async () => {} }
  })
  const world = new MineflayerWorld(bot, 'test')
  const logs = world.visible().filter(block => block.block === 'log')
  const result = await world.act({ action: 'mine', target: 'log' })
  assert.deepEqual(
    { logs, result },
    {
      logs: [{ x: 1, y: 64, z: 0, block: 'log' }],
      result: { ok: true, message: 'mined log', output: { block_removed: true, collected: { log: 1 } }, events: [], executed: true }
    }
  )
})

test('the mine after a toward-move digs the block the move reached, though another in reach comes first', async () => {
  // A has no path from the start, so the move walks next to B; from there A is in reach too.
  const [a, b] = [new Vec3(6, 65, 0), new Vec3(5, 65, 1)]
  const bot = forestBot(new Vec3(0.5, 64, 0.5), [a, b], [a])
  const world = new MineflayerWorld(bot, 'test')
  await world.act({ action: 'move', target: { toward: 'log' } })
  const result = await world.act({ action: 'mine', target: 'log' })
  assert.deepEqual(
    { ok: result.ok, dug: bot.dug, paths: bot.paths },
    { ok: true, dug: [b], paths: [[6, 0], [5, 1]] }
  )
})

// Stone at `stone` with the game's harvest tools; the bot at (0.5, 64, 0.5) holds `held` (item names). Digging stone
// with a pickaxe equipped drops cobblestone. A path, if one is asked for, is recorded and goes nowhere.
function quarryBot (stone, held) {
  const data = minecraftData('1.16.5')
  const times = { [data.itemsByName.wooden_pickaxe.id]: 1150, [data.itemsByName.stone_pickaxe.id]: 600 }
  let standing = true
  let items = held.map(name => ({ name, type: data.itemsByName[name].id, count: 1 }))
  const block = {
    name: 'stone',
    position: stone,
    harvestTools: data.blocksByName.stone.harvestTools,
    digTime: type => times[type] ?? 7500
  }
  const bot = Object.assign(new EventEmitter(), {
    paths: [],
    equipped: [],
    dug: [],
    entity: { position: new Vec3(0.5, 64, 0.5) },
    entities: {},
    inventory: { items: () => items },
    findBlocks: () => standing ? [stone] : [],
    blockAt: at => standing && at.equals(stone) ? block : { name: 'air', position: at },
    equip: async item => { bot.equipped.push(item.name) },
    dig: async () => {
      standing = false
      bot.dug.push(stone)
      if (bot.equipped.length) items = [...items, { name: 'cobblestone', type: 0, count: 1 }]
    },
    pathfinder: { setGoal () {}, goto: async goal => { bot.paths.push(goal.constructor.name) } }
  })
  return bot
}

test('mine stone equips the wooden pickaxe held, digs, and says so', async () => {
  const bot = quarryBot(new Vec3(1, 64, 0), ['oak_planks', 'wooden_pickaxe'])
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'mine', target: 'stone' })
  assert.deepEqual(
    { result, equipped: bot.equipped },
    {
      result: {
        ok: true,
        message: 'mined stone with wooden_pickaxe',
        output: { block_removed: true, collected: { cobblestone: 1 }, tool: 'wooden_pickaxe' },
        events: [],
        executed: true
      },
      equipped: ['wooden_pickaxe']
    }
  )
})

test('mine stone with no pickaxe held is refused before walking or digging, executed false', async () => {
  const bot = quarryBot(new Vec3(5, 64, 0), ['oak_planks'])
  const result = await new MineflayerWorld(bot, 'test').act({ action: 'mine', target: 'stone' })
  assert.deepEqual(
    { result, paths: bot.paths, dug: bot.dug },
    {
      result: { ok: false, message: 'mine: no held tool harvests stone', output: null, events: [], executed: false },
      paths: [],
      dug: []
    }
  )
})

test('mine stone with two pickaxes held equips the faster one', async () => {
  const bot = quarryBot(new Vec3(1, 64, 0), ['wooden_pickaxe', 'stone_pickaxe'])
  const { message } = await new MineflayerWorld(bot, 'test').act({ action: 'mine', target: 'stone' })
  assert.deepEqual({ message, equipped: bot.equipped }, { message: 'mined stone with stone_pickaxe', equipped: ['stone_pickaxe'] })
})
