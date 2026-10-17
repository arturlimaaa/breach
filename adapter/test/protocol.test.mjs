import { test } from 'node:test'
import assert from 'node:assert/strict'
import { once } from 'node:events'
import minecraftData from 'minecraft-data'
import mc from 'minecraft-protocol'
import mineflayer from 'mineflayer'
import { normalize } from '../craft.mjs'
import { MineflayerWorld } from '../world.mjs'

const data = minecraftData('1.16.5')
const STICK_GRID = 'oak_planks,,oak_planks,'

const toNotch = item => item ? { present: true, itemId: data.itemsByName[item.name].id, itemCount: item.count } : { present: false }
const same = (claimed, item) => claimed.present
  ? !!item && claimed.itemId === data.itemsByName[item.name].id && claimed.itemCount === item.count
  : !item

// A real mineflayer bot against the player's 2x2 grid as a vanilla 1.16.5 server runs it. A click that changes the grid
// sends the result slot before the transaction. Taking the result uses one item per grid slot, and the server does not
// resend those slots. A click whose claimed item differs from the slot is rejected with a full resync.
async function session (t, stacks, recipe) {
  const slots = Array(46).fill(null)
  for (const [slot, name, count] of stacks) slots[slot] = { name, count }
  let carried = null
  let commands = 0
  const server = mc.createServer({ 'online-mode': false, version: '1.16.5', host: '127.0.0.1', port: 0 })
  await once(server, 'listening')
  server.on('playerJoin', client => {
    client.write('login', { ...data.loginPacket, entityId: 1 })
    client.write('spawn_position', { location: { x: 8, y: 64, z: -24 } })
    client.write('window_items', { windowId: 0, items: slots.map(toNotch) })
    // Commands land a few ticks later, as on a real server.
    client.on('chat', ({ message }) => setTimeout(() => {
      const [command, , item, count] = message.split(' ')
      if (command === '/clear') slots.fill(null, 1)
      if (command === '/give') slots[slots.findIndex((s, i) => i >= 9 && i < 45 && !s)] = { name: item, count: Number(count) }
      commands += 1
      client.write('window_items', { windowId: 0, items: slots.map(toNotch) })
    }, 50))
    client.on('window_click', ({ windowId, slot, mouseButton, action, mode, item }) => {
      let returned = slot >= 0 && slots[slot] ? { ...slots[slot] } : null
      if (mode === 1) {
        slots[slots.findIndex((s, i) => i >= 9 && i < 45 && !s)] = slots[slot]
        slots[slot] = null
        returned = null
      } else if (slot === 0) {
        if (slots[0] && !carried) {
          carried = slots[0]
          for (let s = 1; s <= 4; s++) if (slots[s] && --slots[s].count === 0) slots[s] = null
        }
      } else if (slot >= 0 && mouseButton === 0) {
        if (carried && slots[slot]?.name === carried.name) {
          slots[slot].count += carried.count
          carried = null
        } else {
          [carried, slots[slot]] = [slots[slot], carried]
        }
      } else if (slot >= 0 && !slots[slot] && carried) {
        slots[slot] = { name: carried.name, count: 1 }
        if (--carried.count === 0) carried = null
      }
      if (slot >= 0 && slot <= 4) {
        slots[0] = recipe(slots.slice(1, 5).map(s => s?.name ?? '').join())
        client.write('set_slot', { windowId: 0, slot: 0, item: toNotch(slots[0]) })
      }
      const accepted = same(item, returned)
      client.write('transaction', { windowId, action, accepted })
      if (!accepted) client.write('window_items', { windowId: 0, items: slots.map(toNotch) })
    })
  })
  const { port } = server.socketServer.address()
  const bot = mineflayer.createBot({ host: '127.0.0.1', port, username: 'breach', version: '1.16.5', auth: 'offline' })
  t.after(() => {
    bot.end()
    server.close()
  })
  await once(bot, 'setWindowItems:0')
  const serverInventory = () => {
    const counts = {}
    for (const s of slots.slice(9, 45).filter(Boolean)) counts[normalize(s.name)] = (counts[normalize(s.name)] ?? 0) + s.count
    return { counts, grid: slots.slice(1, 5).filter(Boolean).length, carried }
  }
  return { world: new MineflayerWorld(bot, 'mc/test'), serverInventory, commands: () => commands }
}

const sticks = count => grid => grid === STICK_GRID ? { name: 'stick', count } : null

test('craft lays a vanilla multiset in its shape and reports the delta both sides agree on', async (t) => {
  const { world, serverInventory } = await session(t, [[36, 'oak_planks', 3]], sticks(4))
  const result = await world.act({ action: 'craft', target: 'stick', grid: { planks: 2 } })
  assert.deepEqual(
    { result, client: world.inventory(), server: serverInventory() },
    {
      result: { ok: true, message: 'crafted 4 stick', output: { planks: -2, stick: 4 }, events: [], executed: true },
      client: { planks: 1, stick: 4 },
      server: { counts: { planks: 1, stick: 4 }, grid: 0, carried: null }
    }
  )
})

test('craft under a changed count reports the changed count', async (t) => {
  const { world } = await session(t, [[36, 'oak_planks', 2]], sticks(2))
  const result = await world.act({ action: 'craft', target: 'stick', grid: { planks: 2 } })
  assert.deepEqual(result, { ok: true, message: 'crafted 2 stick', output: { planks: -2, stick: 2 }, events: [], executed: true })
})

test('probe reads the result slot and puts every ingredient back', async (t) => {
  const { world, serverInventory } = await session(t, [[36, 'oak_planks', 3]], sticks(4))
  const result = await world.act({ action: 'probe', target: 'stick', grid: { planks: 2 } })
  assert.deepEqual(
    { result, client: world.inventory(), server: serverInventory() },
    {
      result: { ok: true, message: 'output slot shows 4 stick', output: { stick: 4 }, events: [], executed: true },
      client: { planks: 3 },
      server: { counts: { planks: 3 }, grid: 0, carried: null }
    }
  )
})

test('reset centers the border on the world spawn and returns only after /clear and /give land', async (t) => {
  const { world, commands } = await session(t, [[36, 'oak_planks', 4]], sticks(4))
  const message = await world.reset({ planks: 4 })
  assert.deepEqual(
    { message, commands: commands(), inventory: world.inventory() },
    {
      message: '/worldborder center 8 -24; /worldborder set 256; /clear; /give @s oak_planks 4',
      commands: 4,
      inventory: { planks: 4 }
    }
  )
})

test('a grid with no result fails the craft and puts the ingredients back', async (t) => {
  const { world, serverInventory } = await session(t, [[36, 'oak_planks', 3]], sticks(4))
  const result = await world.act({ action: 'craft', target: 'stick', grid: { planks: 3 } })
  assert.deepEqual(
    { result, client: world.inventory(), server: serverInventory() },
    {
      result: { ok: false, message: 'output slot empty', output: {}, events: [], executed: true },
      client: { planks: 3 },
      server: { counts: { planks: 3 }, grid: 0, carried: null }
    }
  )
})

test('a craft short of ingredients, or a 3x3 craft with no table in reach, is refused without executing', async (t) => {
  const { world } = await session(t, [[36, 'oak_planks', 3], [37, 'stick', 2]], sticks(4))
  const short = await world.act({ action: 'craft', target: 'stick', grid: { planks: 4 } })
  const tableless = await world.act({ action: 'craft', target: 'wooden_pickaxe', grid: { planks: 3, stick: 2 } })
  assert.deepEqual({ short, tableless }, {
    short: { ok: false, message: 'missing {"planks":1}', output: null, events: [], executed: false },
    tableless: { ok: false, message: 'craft: no crafting table within 16 blocks', output: null, events: [], executed: false }
  })
})
