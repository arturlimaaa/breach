import { setTimeout as sleep } from 'node:timers/promises'
import { isDeepStrictEqual } from 'node:util'
import mineflayer from 'mineflayer'
import pathfinderPlugin from 'mineflayer-pathfinder'
import { Vec3 } from 'vec3'
import { clear, fill, normalize, slotsFor } from './craft.mjs'
import { glance, HEADINGS, touchesAir } from './look.mjs'

const { pathfinder, Movements, goals } = pathfinderPlugin
const STEP_MS = 60_000
const PATH_MS = 20_000
const INVENTORY_MS = 3_000 // how long place waits for its inventory change, and mine walks to a drop
const PICKUP_MS = 1_000 // a dug block's drop lands and passes its pickup delay within this
const RESET_MS = 5_000
const OPEN_MS = 5_000
const RADIUS = 8
const APPROACHES = 3 // visible blocks of a type a move or mine tries before it answers no path
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
  // Set once the world has evaluated the step's action. A step refused before that point reports executed false, so the
  // core takes it as no evidence about a rule.
  #executed = false
  // The block the last toward-move reached, first in line for the next mine.
  #approached = null

  constructor (bot, server, stepMs = STEP_MS) {
    this.bot = bot
    this.server = server
    this.stepMs = stepMs
  }

  // Returns the commands issued, so a run manifest can record the start state. The border is set here because a
  // command piped into the server console before the world loads has no world to act on.
  // ponytail: clears and refills the inventory only; restart the server from the saved world for fresh blocks.
  async reset (inventory) {
    const { bot } = this
    this.#approached = null
    if (bot.currentWindow) await bot.closeWindow(bot.currentWindow)
    const setup = [`/worldborder center ${bot.spawnPoint.x} ${bot.spawnPoint.z}`, '/worldborder set 256', '/clear']
    for (const command of setup) bot.chat(command)
    // Wait for the clear to land, or an inventory that already matches the task would pass before it.
    if (!await settle(() => bot.inventory.items().length === 0, RESET_MS)) {
      throw new Error('/clear did not land; the bot needs op level 2')
    }
    const gives = Object.entries(inventory).map(([item, n]) => `/give @s ${GIVE.get(item) ?? item} ${n}`)
    for (const give of gives) bot.chat(give)
    if (!await settle(() => isDeepStrictEqual(this.inventory(), inventory), RESET_MS)) {
      throw new Error(`inventory is ${JSON.stringify(this.inventory())} after /give`)
    }
    return [...setup, ...gives].join('; ')
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
    this.#executed = false
    try {
      const result = await within(this.#run(action, target, grid), this.stepMs, 'step', () => this.#cancel())
      return { output: null, ...result, events, executed: this.#executed }
    } catch (err) {
      return { ok: false, message: `${action}: ${err.message}`, output: null, events, executed: this.#executed }
    } finally {
      for (const [name, listener] of Object.entries(listeners)) bot.off(name, listener)
    }
  }

  async #run (action, target, grid) {
    switch (action) {
      case 'move': return this.#move(target)
      case 'look': return this.#look()
      case 'mine': return this.#mine(target)
      case 'place': return this.#place(target)
      case 'craft': return this.#craft(grid)
      case 'probe': return this.#probe(grid)
      default: throw new Error('unknown action')
    }
  }

  async #move (target) {
    if (target?.toward) {
      this.#approached = await this.#approach(target.toward, `toward ${target.toward}`)
      this.#executed = true
      return { ok: true, message: `moved toward ${target.toward}` }
    }
    if (target?.heading !== undefined) return this.#head(target.heading, target.blocks)
    const offset = DIRECTIONS.get(target)
    if (!offset) throw new Error('target must be north, south, east, west, {"toward": block}, or {"heading": h, "blocks": n}')
    const { x, z } = this.position()
    await this.#goto(new goals.GoalXZ(x + offset[0], z + offset[1]), target)
    this.#executed = true
    return { ok: true, message: `moved ${target}` }
  }

  // Paths to the point n blocks along a heading, or failing that to the points n/2 and n/4 along the same line, so a
  // blocked line still makes progress. Every point is measured from where the move started.
  async #head (heading, blocks) {
    const offset = HEADINGS.get(heading)
    if (!offset || !Number.isInteger(blocks) || blocks < 1) {
      throw new Error('heading must be N, NE, E, SE, S, SW, W, or NW, and blocks a positive integer')
    }
    const { x, z } = this.position()
    this.#executed = true
    for (const k of new Set([blocks, Math.floor(blocks / 2), Math.floor(blocks / 4)].filter(k => k > 0))) {
      try {
        // Within one block of the point, diagonals included.
        await this.#goto(new goals.GoalNearXZ(x + k * offset[0], z + k * offset[1], 1.5), `${k} blocks ${heading}`)
        return { ok: true, message: `moved ${k} blocks ${heading}`, output: this.position() }
      } catch {
        // A shorter stretch of the line may still have a path.
      }
    }
    return { ok: false, message: `no path ${heading}`, output: this.position() }
  }

  async #mine (target) {
    const { bot } = this
    // The tool is chosen, or the mine refused, before any walking. Blocks of one generic name share their harvest tools.
    const sample = this.#inSight().find(block => normalize(block.name) === target)
    const tool = sample ? this.#tool(sample) : null
    const block = await this.#approach(target, `to ${target}`, this.#approached)
    this.#approached = null
    if (tool) await bot.equip(tool, 'hand')
    const before = this.inventory()
    this.#executed = true
    await bot.dig(block)
    await this.#collect(block, before)
    // dig() clears the block locally at once; a dig the server refused comes back as a block update during the wait.
    const now = bot.blockAt(block.position)
    const removed = now !== null && normalize(now.name) !== target
    return {
      ok: removed,
      message: removed ? `mined ${target}${tool ? ` with ${tool.name}` : ''}` : `${target} is still there`,
      output: { block_removed: removed, collected: diff(before, this.inventory()), ...(tool && { tool: tool.name }) }
    }
  }

  // The fastest held item that harvests `block`, or null when bare hands are as fast. Stone dug without a pickaxe drops
  // nothing, which would read as a changed drop rule, so a block that needs a tool none of the held items is refuses.
  #tool (block) {
    const time = item => block.digTime(item?.type ?? null, false, false, false)
    const fastest = (best, item) => time(item) < time(best) ? item : best
    const held = this.bot.inventory.items()
    if (!block.harvestTools) return held.reduce(fastest, null)
    const harvesters = held.filter(item => block.harvestTools[item.type])
    if (!harvesters.length) throw new Error(`no held tool harvests ${normalize(block.name)}`)
    return harvesters.reduce(fastest)
  }

  // A drop that rolls more than about 1.4 blocks from the bot is not picked up where it stands, so walk onto it.
  async #collect (block, before) {
    const { bot } = this
    const changed = () => !isDeepStrictEqual(this.inventory(), before)
    if (await settle(changed, PICKUP_MS)) return
    const center = block.position.offset(0.5, 0.5, 0.5)
    const off = entity => Math.hypot(entity.position.x - center.x, entity.position.z - center.z)
    const [drop] = Object.values(bot.entities)
      .filter(entity => entity.name === 'item' && entity.position.y <= center.y && off(entity) <= 2)
      .sort((a, b) => off(a) - off(b))
    if (!drop) return
    const { x, y, z } = drop.position.floored()
    await this.#goto(new goals.GoalBlock(x, y, z), 'to the drop', INVENTORY_MS).catch(() => {})
    await settle(changed, PICKUP_MS)
  }

  async #place (target) {
    const { bot } = this
    const item = bot.inventory.items().find(stack => normalize(stack.name) === target)
    if (!item) throw new Error(`no ${target} held`)
    const { position } = bot.entity
    const feet = position.floored()
    // The block must not overlap the bot, whose 0.6-wide box can reach 0.15 into a neighboring cell.
    const spot = [...DIRECTIONS.values()].map(([dx, dz]) => feet.offset(dx, 0, dz)).find(at =>
      bot.blockAt(at)?.boundingBox === 'empty' &&
      bot.blockAt(at.offset(0, -1, 0))?.boundingBox === 'block' &&
      Math.max(Math.abs(at.x + 0.5 - position.x), Math.abs(at.z + 0.5 - position.z)) >= 0.8)
    if (!spot) throw new Error(`no adjacent solid spot for ${target}`)
    const before = this.inventory()
    await bot.equip(item, 'hand')
    // placeBlock resolves only once the server shows the new block there. The used item arrives separately.
    this.#executed = true
    await bot.placeBlock(bot.blockAt(spot.offset(0, -1, 0)), new Vec3(0, 1, 0))
    await settle(() => !isDeepStrictEqual(this.inventory(), before), INVENTORY_MS)
    return { ok: true, message: `placed ${target} at ${spot.x},${spot.y},${spot.z}`, output: diff(before, this.inventory()) }
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

  // Fills the layout into the inventory's 2x2 grid or the nearest table's 3x3 grid, runs `use` on the window,
  // then moves leftovers back. A 1.16.5 server sends the result slot before confirming the click that changed the grid,
  // so the window holds the server's result once `fill` returns. Crafting never places a table; `place` does.
  async #atGrid ({ size, slots }, use) {
    const { bot } = this
    if (bot.currentWindow) await bot.closeWindow(bot.currentWindow)
    const window = size === 2 ? bot.inventory : await this.#openTable()
    try {
      await clear(bot, window, size)
      await fill(bot, window, slots)
      this.#executed = true
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
    if (bot.entity.position.distanceTo(table.position) > 4) await this.#goto(reach(table.position), 'to crafting_table')
    return within(bot.openBlock(table), OPEN_MS, 'opening the crafting table')
  }

  async #goto (goal, label, ms = PATH_MS) {
    const { bot } = this
    try {
      await within(bot.pathfinder.goto(goal), ms, `path ${label}`, () => bot.pathfinder.setGoal(null))
    } finally {
      // goto rejects on a partial path while the pathfinder keeps walking it; a step ends where the bot stands.
      bot.pathfinder.setGoal(null)
    }
    // goto also resolves when no path exists.
    if (!this.#reached(goal)) throw new Error(`no path ${label}`)
  }

  // The pathfinder counts a goal as reached one block up too.
  #reached (goal) {
    const at = this.bot.entity.position.floored()
    return goal.isEnd(at) || goal.isEnd(at.offset(0, 1, 0))
  }

  // Of the nearest visible blocks of a type, the first already within reach, else the first a path reaches. Move and
  // mine share it, so a mine digs the block a toward-move went to.
  async #approach (name, label, first = null) {
    const seen = this.#inSight().filter(block => normalize(block.name) === name)
    const kept = first && seen.find(block => block.position.equals(first.position))
    const blocks = (kept ? [kept, ...seen.filter(block => block !== kept)] : seen).slice(0, APPROACHES)
    if (!blocks.length) throw new Error(`no ${name} in sight`)
    const near = blocks.find(block => this.#reached(reach(block.position)))
    if (near) return near
    for (const block of blocks) {
      try {
        await this.#goto(reach(block.position), label)
        return block
      } catch {
        // The next one may have a path.
      }
    }
    throw new Error(`no path ${label}`)
  }

  #look () {
    this.#executed = true
    const { x, y, z } = this.position()
    const seen = glance((bx, by, bz) => this.bot.blockAt(new Vec3(bx, by, bz), false)?.name ?? null, x, y, z)
    return { ok: true, message: `blocks along ${Object.keys(seen).length} headings`, output: seen }
  }

  // Non-air blocks within RADIUS that touch air, nearest first: the look rule. A ray to each block's center, the earlier
  // test, misses a trunk under a canopy one block away; whether a block can be reached is the pathfinder's call.
  #inSight () {
    const { bot } = this
    const nameAt = (x, y, z) => bot.blockAt(new Vec3(x, y, z), false)?.name ?? null
    return bot.findBlocks({ matching: block => block && !AIR.has(block.name), maxDistance: RADIUS, count: Infinity })
      .filter(({ x, y, z }) => touchesAir(nameAt, x, y, z))
      .map(position => bot.blockAt(position))
  }

  #cancel () {
    const { bot } = this
    bot.pathfinder.setGoal(null)
    bot.stopDigging()
    if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  }
}

// In the block's column or one of the eight around it, and within 4.5 blocks of it, measured from the cell under the
// block to the feet, which tracks the eyes to within half a block. A diagonal neighbor digs and picks up the drop as
// well as a side one. pathfinder's GoalLookAtBlock measures reach from 1.6 blocks below the feet instead, so it
// refuses logs three or more blocks up a trunk.
const reach = position => new goals.GoalCompositeAll([
  new goals.GoalNearXZ(position.x, position.z, 1.5),
  new goals.GoalNear(position.x, position.y - 1, position.z, 4.5)
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
