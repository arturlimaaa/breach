import { glance, HEADINGS } from './look.mjs'

// In-memory World with the adapter's interface: a flat block list and a small inventory. It can only mine, look, and
// move along a heading, which always reaches its point.
export class FakeWorld {
  server = 'fake/flat'
  #items = {}
  #position = { x: 0, y: 64, z: 0 }

  constructor (blocks) {
    this.blocks = blocks.map(block => ({ ...block }))
  }

  async reset (inventory) {
    this.#items = { ...inventory }
    return ['/clear', ...Object.entries(inventory).map(([item, n]) => `/give @s ${item} ${n}`)].join('; ')
  }

  position () {
    return { ...this.#position }
  }

  inventory () {
    return { ...this.#items }
  }

  visible () {
    return this.blocks.map(block => ({ ...block }))
  }

  async act ({ action, target }) {
    if (action === 'move' && target?.heading) {
      const [dx, dz] = HEADINGS.get(target.heading)
      this.#position = { ...this.#position, x: this.#position.x + dx * target.blocks, z: this.#position.z + dz * target.blocks }
      return { ok: true, message: `moved ${target.blocks} blocks ${target.heading}`, output: this.position(), events: [], executed: true }
    }
    if (action === 'look') {
      const { x, y, z } = this.position()
      const seen = glance((bx, by, bz) => this.blocks.find(b => b.x === bx && b.y === by && b.z === bz)?.block ?? 'air', x, y, z)
      return { ok: true, message: `blocks along ${Object.keys(seen).length} headings`, output: seen, events: [], executed: true }
    }
    const index = action === 'mine' ? this.blocks.findIndex(block => block.block === target) : -1
    if (index < 0) return { ok: false, message: `fake world cannot ${action} ${target}`, output: null, events: [], executed: false }
    this.blocks.splice(index, 1)
    this.#items[target] = (this.#items[target] ?? 0) + 1
    return { ok: true, message: `mined ${target}`, output: { block_removed: true, collected: { [target]: 1 } }, events: [], executed: true }
  }
}
