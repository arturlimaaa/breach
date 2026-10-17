import { setTimeout as sleep } from 'node:timers/promises'
import { isDeepStrictEqual } from 'node:util'
import mineflayer from 'mineflayer'
import pathfinderPlugin from 'mineflayer-pathfinder'
import { clear, normalize, place, slotsFor } from './craft.mjs'

const { pathfinder, Movements, goals } = pathfinderPlugin
const STEP_MS = 60_000
const PATH_MS = 20_000
const COLLECT_MS = 3_000
const RESET_MS = 5_000
const OPEN_MS = 5_000
const RADIUS = 8
const DIRECTIONS = new Map([['north', [0, -1]], ['south', [0, 1]], ['east', [1, 0]], ['west', [-1, 0]]])
const AIR = new Set(['air', 'cave_air', 'void_air'])
const GIVE = new Map([['log', 'oak_log'], ['planks', 'oak_planks']])

export function createBot ({ host, port, username }) {
  const bot = mineflayer.createBot({ host, port, username, version: '1.16.5', auth: 'offline' })
  bot.loadPlugin(pathfinder)
  bot.once('spawn', () => {
    // Paths must leave the inventory alone: no digging through, no pillaring or bridging with held blocks.
    bot.pathfinder.setMovements(Object.assign(new Movements(bot), { canDig: false, allow1by1towers: false, scafoldingBlocks: [] }))
  })
  return bot
}

// Rejects after `ms`, calling `cancel` first. The timer is unref'd so a pending bound never holds the process open.
export function within (work, ms, label, cancel = () => {}) {
  let timer
  const timeout = new Promise((resolve, reject) => {
    timer = setTimeout(() => {
      cancel()
      reject(new Error(`${label} timed out after ${ms / 1000} s`))
    }, ms).unref()
  })
  return Promise.race([work, timeout]).finally(() => clearTimeout(timer))
}

export class MineflayerWorld {
  constructor (bot, server, stepMs = STEP_MS) {
    this.bot = bot
    this.server = server
    this.stepMs = stepMs
  }

  // ponytail: clears and refills the inventory only; restart the server from the saved world for fresh blocks.
  async reset (inventory) {
    const { bot } = this
    if (bot.currentWindow) await bot.closeWindow(bot.currentWindow)
    bot.chat('/clear')
    // Wait for the clear to land, or an inventory that already matches the task would pass before it.
    if (!await settle(() => bot.inventory.items().length === 0, RESET_MS)) {
      throw new Error('/clear did not land; the bot needs op level 2')
    }
    for (const [item, n] of Object.entries(inventory)) bot.chat(`/give @s ${GIVE.get(item) ?? item} ${n}`)
    if (!await settle(() => isDeepStrictEqual(this.inventory(), inventory), RESET_MS)) {
      throw new Error(`inventory is ${JSON.stringify(this.inventory())} after /give`)
    }
  }

  position () {
    const { x, y, z } = this.bot.entity.position.floored()
    return { x, y, z }
  }

  inventory () {
    const counts = {}
    for (const { name, count } of this.bot.inventory.items()) counts[normalize(name)] = (counts[normalize(name)] ?? 0) + count
    return counts
  }

  visible () {
    return this.#inSight().map(({ position: { x, y, z }, name }) => ({ x, y, z, block: normalize(name) }))
  }

  // ponytail: a timed-out step keeps running in the background until its inner bounds expire; queue on it if steps overlap.
  async act ({ action, target, grid }) {
    const { bot } = this
    const events = []
    const listeners = {
      death: () => events.push('death'),
      entityHurt: entity => { if (entity === bot.entity) events.push('damage') },
      kicked: () => events.push('kicked')
    }
    for (const [name, listener] of Object.entries(listeners)) bot.on(name, listener)
    try {
      return { output: null, ...await within(this.#run(action, target, grid), this.stepMs, 'step', () => this.#cancel()), events }
    } catch (err) {
      return { ok: false, message: `${action}: ${err.message}`, output: null, events }
    } finally {
      for (const [name, listener] of Object.entries(listeners)) bot.off(name, listener)
    }
  }

  async #run (action, target, grid) {
    switch (action) {
      case 'move': return this.#move(target)
      case 'look': return { ok: true, message: `${this.#inSight().length} blocks in sight` }
      case 'mine': return this.#mine(target)
      case 'craft': return this.#craft(grid)
      case 'probe': return this.#probe(grid)
      default: throw new Error('unknown action')
    }
  }

  async #move (target) {
    if (target?.toward) {
      const block = this.#nearest(target.toward)
      if (!block) throw new Error(`no ${target.toward} in sight`)
      await this.#goto(reach(this.bot, block.position), `toward ${target.toward}`)
      return { ok: true, message: `moved toward ${target.toward}` }
    }
    const offset = DIRECTIONS.get(target)
    if (!offset) throw new Error('target must be north, south, east, west, or {"toward": block}')
    const { x, z } = this.position()
    await this.#goto(new goals.GoalXZ(x + offset[0], z + offset[1]), target)
    return { ok: true, message: `moved ${target}` }
  }

  async #mine (target) {
    const { bot } = this
    const block = this.#nearest(target)
    if (!block) throw new Error(`no ${target} in sight`)
    await this.#goto(reach(bot, block.position), `to ${target}`)
    const tool = bot.pathfinder.bestHarvestTool(block)
    if (tool) await bot.equip(tool, 'hand')
    const before = this.inventory()
    await bot.dig(block)
    await settle(() => !isDeepStrictEqual(this.inventory(), before), COLLECT_MS)
    // dig() clears the block locally at once; a dig the server refused comes back as a block update during the wait.
    const now = bot.blockAt(block.position)
    const removed = now !== null && normalize(now.name) !== target
    return {
      ok: removed,
      message: removed ? `mined ${target}` : `${target} is still there`,
      output: { block_removed: removed, collected: diff(before, this.inventory()) }
    }
  }

  async #craft (grid) {
    const layout = this.#layout(grid)
    const missing = this.#missing(layout.slots)
    if (missing) return { ok: false, message: `missing ${JSON.stringify(missing)}` }
    const before = this.inventory()
    const result = await this.#atGrid(layout, async window => {
      const result = window.slots[0]
      if (!result) return null
      await this.bot.putAway(0)
      // Taking the result uses one item from each grid slot, and 1.16.5 servers do not resend those slots.
      for (const [slot] of layout.slots) if (--window.slots[slot].count === 0) window.updateSlot(slot, null)
      return result
    })
    if (!result) return { ok: false, message: 'output slot empty', output: {} }
    return { ok: true, message: `crafted ${result.count} ${normalize(result.name)}`, output: diff(before, this.inventory()) }
  }

  async #probe (grid) {
    const layout = this.#layout(grid)
    if (this.#missing(layout.slots)) return { ok: true, message: 'cannot place what is not held', output: {} }
    const result = await this.#atGrid(layout, window => window.slots[0])
    if (!result) return { ok: true, message: 'output slot is empty', output: {} }
    const item = normalize(result.name)
    return { ok: true, message: `output slot shows ${result.count} ${item}`, output: { [item]: result.count } }
  }

  #layout (grid) {
    if (!grid) throw new Error('needs a grid')
    for (const size of [2, 3]) {
      const slots = slotsFor(grid, size)
      if (slots?.length) return { size, slots }
    }
    throw new Error('grid must be {item: n} or rows of items, at most 3x3')
  }

  #missing (slots) {
    const have = this.inventory()
    const need = {}
    for (const [, item] of slots) need[item] = (need[item] ?? 0) + 1
    const short = Object.entries(need).filter(([item, n]) => (have[item] ?? 0) < n)
    return short.length ? Object.fromEntries(short.map(([item, n]) => [item, n - (have[item] ?? 0)])) : null
  }

  // Places the layout in the inventory's 2x2 grid or the nearest table's 3x3 grid, runs `use` on the window,
  // then moves leftovers back. A 1.16.5 server sends the result slot before confirming the click that changed the grid,
  // so the window holds the server's result once `place` returns.
  async #atGrid ({ size, slots }, use) {
    const { bot } = this
    if (bot.currentWindow) await bot.closeWindow(bot.currentWindow)
    const window = size === 2 ? bot.inventory : await this.#openTable()
    try {
      await clear(bot, window, size)
      await place(bot, window, slots)
      return await use(window)
    } finally {
      await clear(bot, window, size)
      if (window !== bot.inventory) await bot.closeWindow(window)
    }
  }

  async #openTable () {
    const { bot } = this
    const table = bot.findBlock({ matching: block => block?.name === 'crafting_table', maxDistance: 16 })
    if (!table) throw new Error('no crafting table within 16 blocks')
    if (bot.entity.position.distanceTo(table.position) > 4) await this.#goto(reach(bot, table.position), 'to crafting_table')
    return within(bot.openBlock(table), OPEN_MS, 'opening the crafting table')
  }

  async #goto (goal, label) {
    const { bot } = this
    await within(bot.pathfinder.goto(goal), PATH_MS, `path ${label}`, () => bot.pathfinder.setGoal(null))
    // goto also resolves when no path exists. The pathfinder counts the goal as reached one block up too.
    const at = bot.entity.position.floored()
    if (!goal.isEnd(at) && !goal.isEnd(at.offset(0, 1, 0))) throw new Error(`no path ${label}`)
  }

  // Non-air blocks within RADIUS with a clear line from the bot's eyes, nearest first.
  #inSight () {
    const { bot } = this
    return bot.findBlocks({ matching: block => block && !AIR.has(block.name), maxDistance: RADIUS, count: Infinity })
      .map(position => bot.blockAt(position))
      .filter(block => block && bot.canSeeBlock(block))
  }

  #nearest (name) {
    return this.#inSight().find(block => normalize(block.name) === name) ?? null
  }

  #cancel () {
    const { bot } = this
    bot.pathfinder.setGoal(null)
    bot.stopDigging()
    if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  }
}

// Horizontally next to the block with a clear line to one of its faces, so its drop lands within pickup range.
const reach = (bot, position) => new goals.GoalCompositeAll([
  new goals.GoalNearXZ(position.x, position.z, 1),
  new goals.GoalLookAtBlock(position, bot.world)
])

async function settle (check, ms) {
  const deadline = Date.now() + ms
  while (!check() && Date.now() < deadline) await sleep(100)
  return check()
}

function diff (before, after) {
  const delta = {}
  for (const item of new Set([...Object.keys(before), ...Object.keys(after)])) {
    const n = (after[item] ?? 0) - (before[item] ?? 0)
    if (n) delta[item] = n
  }
  return delta
}
