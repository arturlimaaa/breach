import { test } from 'node:test'
import assert from 'node:assert/strict'
import { glance } from '../look.mjs'

// Named cells, air everywhere else.
const world = cells => (x, y, z) => cells[`${x},${y},${z}`] ?? 'air'
const around = (x, y, z, name) => Object.fromEntries(
  [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]].map(([a, b, c]) => [`${x + a},${y + b},${z + c}`, name])
)

test('look keeps the nearest known block per heading in a sheared corridor 7 wide and 48 long, center lane first', () => {
  const cells = {
    '12,64,1': 'stone', // E: lane 1 loses to lane -1 at the same step
    '12,64,-1': 'oak_log',
    '18,64,-20': 'crafting_table', // NE: step 20, lane -2 of the sheared corridor
    '0,64,48': 'birch_log', // S: the last step
    '0,64,-49': 'oak_log', // N: one step too far
    '-15,64,4': 'oak_log', // W: one lane too wide
    '-30,70,30': 'spruce_log' // SW: six above the feet
  }
  assert.deepEqual(glance(world(cells), 0, 64, 0), {
    E: { block: 'log', distance: 12 },
    NE: { block: 'crafting_table', distance: 20 },
    S: { block: 'log', distance: 48 },
    SW: { block: 'log', distance: 30 }
  })
})

test('look counts only known blocks that touch air, so buried stone and cave walls stay out', () => {
  const cells = {
    '0,60,-12': 'stone', // N: buried in dirt
    ...around(0, 60, -12, 'dirt'),
    '12,64,0': 'coal_ore', // E: in a cave
    ...around(12, 64, 0, 'cave_air'),
    '0,63,15': 'stone', // S: air above it
    '-12,63,0': 'grass_block', // W: not a block the core knows, then a log one lane over
    '-12,64,1': 'spruce_log'
  }
  assert.deepEqual(glance(world(cells), 0, 64, 0), {
    S: { block: 'stone', distance: 15 },
    W: { block: 'log', distance: 12 }
  })
})

test('look with a target reports the nearest block of that type per heading, past nearer known blocks', () => {
  const cells = {
    '3,64,0': 'oak_log', // E: a log masks the stone behind it unless the look names stone
    '9,64,1': 'stone',
    '0,64,-5': 'oak_log' // N: no stone at all
  }
  assert.deepEqual(
    { plain: glance(world(cells), 0, 64, 0), stone: glance(world(cells), 0, 64, 0, 'stone') },
    {
      plain: { E: { block: 'log', distance: 3 }, N: { block: 'log', distance: 5 } },
      stone: { E: { block: 'stone', distance: 9 } }
    }
  )
})
