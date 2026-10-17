import { glance } from './look.mjs'

// In-memory World with the adapter's interface: a flat block list and a small inventory. It can only mine and look.
export class FakeWorld {
  server = 'fake/flat'
  #items = {}

  constructor (blocks) {
    this.blocks = blocks.map(block => ({ ...block }))
  }

  async reset (inventory) {
    this.#items = { ...inventory }
    return ['/clear', ...Object.entries(inventory).map(([item, n]) => `/give @s ${item} ${n}`)].join('; ')
  }

  position () {
    return { x: 0, y: 64, z: 0 }
  }

  inventory () {
    return { ...this.#items }
  }

  visible () {
    return this.blocks.map(block => ({ ...block }))
  }

  async act ({ action, target }) {
    if (action === 'look') {
      const { x, y, z } = this.position()
      const seen = glance((bx, by, bz) => this.blocks.find(b => b.x === bx && b.y === by && b.z === bz)?.block ?? 'air', x, y, z)
      return { ok: true, message: `blocks along ${Object.keys(seen).length} headings`, output: seen, events: [] }
    }
    const index = action === 'mine' ? this.blocks.findIndex(block => block.block === target) : -1
    if (index < 0) return { ok: false, message: `fake world cannot ${action} ${target}`, output: null, events: [] }
    this.blocks.splice(index, 1)
    this.#items[target] = (this.#items[target] ?? 0) + 1
    return { ok: true, message: `mined ${target}`, output: { block_removed: true, collected: { [target]: 1 } }, events: [] }
  }
}
