import { once } from 'node:events'
import { createServer } from 'node:http'
import { text } from 'node:stream/consumers'
import { createBot, MineflayerWorld } from './world.mjs'

// The adapter contract of docs/design.md over a World: reset(inventory) returning the commands it issued, position(),
// inventory(), visible(), act(step).
export function serve (world) {
  let task = null
  let actions = 0
  let queue = Promise.resolve()

  function observation () {
    const inventory = world.inventory()
    const success = (inventory[task.goal] ?? 0) >= task.count
    return {
      server: world.server,
      position: world.position(),
      inventory,
      visible: world.visible(),
      action_count: actions,
      budget: task.budget,
      done: success || actions >= task.budget,
      success
    }
  }

  const routes = {
    'POST /reset': async body => {
      const next = body?.task
      if (typeof next?.goal !== 'string') return [400, { error: 'body must be {task: {goal, count, budget, inventory}}' }]
      const message = await world.reset(next.inventory ?? {})
      task = { count: 1, budget: 150, ...next }
      actions = 0
      return [200, { ...observation(), message }]
    },
    'GET /observe': async () => [200, observation()],
    'POST /step': async step => {
      if (typeof step?.action !== 'string') return [400, { error: 'body must be {action, target, grid}' }]
      const before = observation()
      if (before.done) return [200, { ok: false, message: 'episode is over', output: null, events: [], observation: before }]
      actions += 1
      return [200, { ...await world.act(step), observation: observation() }]
    }
  }

  async function handle (req) {
    const route = routes[`${req.method} ${req.url}`]
    if (!route) return [404, { error: `no route ${req.method} ${req.url}` }]
    if (!task && req.url !== '/reset') return [409, { error: 'POST /reset first' }]
    let body
    try {
      body = JSON.parse((await text(req)) || '{}')
    } catch {
      return [400, { error: 'body is not JSON' }]
    }
    try {
      return await route(body)
    } catch (err) {
      return [500, { error: err.message }]
    }
  }

  // One request at a time: two steps must never drive the bot at once.
  return createServer((req, res) => {
    queue = queue.then(() => handle(req)).then(([status, payload]) => {
      res.writeHead(status, { 'content-type': 'application/json' })
      res.end(JSON.stringify(payload))
    }, err => console.error(err))
  })
}

if (import.meta.main) {
  const host = process.env.MC_HOST ?? '127.0.0.1'
  const port = Number(process.env.MC_PORT ?? 25565)
  const bot = createBot({ host, port, username: process.env.MC_USERNAME ?? 'breach' })
  bot.on('kicked', reason => console.error(`kicked: ${reason}`))
  bot.on('end', reason => {
    console.error(`bot left ${host}:${port}: ${reason}`)
    process.exit(1)
  })
  await once(bot, 'spawn')
  if (process.env.VIEWER_PORT) {
    const { default: viewer } = await import('prismarine-viewer')
    viewer.mineflayer(bot, { port: Number(process.env.VIEWER_PORT), firstPerson: false })
  }
  const world = new MineflayerWorld(bot, `mc/${host}:${port}/${process.env.MC_WORLD ?? 'world'}`)
  const listen = Number(process.env.PORT ?? 3100)
  serve(world).listen(listen, '127.0.0.1', () => console.log(`adapter on http://127.0.0.1:${listen} for ${world.server}`))
}
