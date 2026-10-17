import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import { fill, normalize, slotsFor } from '../craft.mjs'

const PICKAXE = [['planks', 'planks', 'planks'], [null, 'stick', null], [null, 'stick', null]]

// Vanilla cursor clicks: a left click swaps the cursor with the slot, a right click drops one item into an empty slot.
function fakeBot (stacks) {
  const window = {
    slots: [],
    selectedItem: null,
    inventoryStart: 9,
    inventoryEnd: 45,
    items () { return this.slots.slice(9, 45).filter(Boolean) }
  }
  for (const [slot, name, count] of stacks) window.slots[slot] = { slot, name, count }
  const clicks = []
  return {
    inventory: window,
    clicks,
    async clickWindow (slot, button) {
      clicks.push([slot, button])
      if (button === 0) {
        const held = window.selectedItem
        window.selectedItem = window.slots[slot] ?? null
        window.slots[slot] = held && { ...held, slot }
        return
      }
      window.slots[slot] = { slot, name: window.selectedItem.name, count: 1 }
      if (--window.selectedItem.count === 0) window.selectedItem = null
    },
    async putSelectedItemRange () {
      clicks.push('cursor back')
      window.selectedItem = null
    }
  }
}

test('a count map with no vanilla shape fills a 2x2 grid left to right, top to bottom', () => {
  assert.deepEqual(slotsFor({ planks: 2, coal: 1 }, 2), [[1, 'planks'], [2, 'planks'], [3, 'coal']])
})

test('a count map with no vanilla shape fills a 3x3 grid left to right, top to bottom', () => {
  assert.deepEqual(
    slotsFor({ cobblestone: 4, stick: 1 }, 3),
    [[1, 'cobblestone'], [2, 'cobblestone'], [3, 'cobblestone'], [4, 'cobblestone'], [5, 'stick']]
  )
})

test('a count map with a vanilla multiset takes that shape, whatever its key order', () => {
  const slots = grid => slotsFor(grid, 2) ?? slotsFor(grid, 3)
  const cells = grid => slots(grid).map(([slot]) => slot)
  assert.deepEqual(
    {
      planks: cells({ log: 1 }),
      stick: cells({ planks: 2 }),
      crafting_table: cells({ planks: 4 }),
      torch: slots({ stick: 1, coal: 1 }),
      wooden_pickaxe: slots({ stick: 2, planks: 3 }),
      stone_pickaxe: cells({ cobblestone: 3, stick: 2 }),
      furnace: cells({ cobblestone: 8 }),
      ladder: cells({ stick: 7 })
    },
    {
      planks: [1],
      stick: [1, 3],
      crafting_table: [1, 2, 3, 4],
      torch: [[1, 'coal'], [3, 'stick']],
      wooden_pickaxe: [[1, 'planks'], [2, 'planks'], [3, 'planks'], [5, 'stick'], [8, 'stick']],
      stone_pickaxe: [1, 2, 3, 5, 8],
      furnace: [1, 2, 3, 4, 6, 7, 8, 9],
      ladder: [1, 3, 4, 5, 6, 7, 9]
    }
  )
})

test('rows keep their shape in a 2x2 grid', () => {
  assert.deepEqual(slotsFor([['planks'], ['planks']], 2), [[1, 'planks'], [3, 'planks']])
})

test('rows keep their shape in a 3x3 grid', () => {
  assert.deepEqual(slotsFor(PICKAXE, 3), [[1, 'planks'], [2, 'planks'], [3, 'planks'], [5, 'stick'], [8, 'stick']])
})

test('a grid that does not fit or has a bad count gives no slots', () => {
  assert.deepEqual(
    [slotsFor({ planks: 5 }, 2), slotsFor([['stick'], ['stick'], ['stick']], 2), slotsFor({ planks: 10 }, 3), slotsFor({ planks: 1.5 }, 3)],
    [null, null, null, null]
  )
})

test('wood variants take generic names and other ids stay', () => {
  assert.deepEqual(
    ['oak_log', 'stripped_birch_log', 'spruce_planks', 'stick', 'cobblestone'].map(normalize),
    ['log', 'log', 'planks', 'stick', 'cobblestone']
  )
})

test('filling puts one item per slot, switching stacks by generic name, then returns the cursor', async () => {
  const bot = fakeBot([[36, 'oak_planks', 1], [37, 'birch_planks', 3], [38, 'stick', 3]])
  await fill(bot, bot.inventory, slotsFor(PICKAXE, 3))
  assert.deepEqual(bot.clicks, [[36, 0], [1, 1], [37, 0], [2, 1], [3, 1], [38, 0], [5, 1], [8, 1], 'cursor back'])
})

test('the adapter never reads recipe data', async () => {
  const root = new URL('../', import.meta.url)
  const hits = []
  for (const name of (await readdir(root)).filter(name => name.endsWith('.mjs'))) {
    if (/recipesFor|recipesAll|bot\.craft\b|\.recipes\b|prismarine-recipe/.test(await readFile(new URL(name, root), 'utf8'))) hits.push(name)
  }
  assert.deepEqual(hits, [])
})
