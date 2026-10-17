// In-memory World with the adapter's interface: a flat block list and a small inventory. It can only mine.
export class FakeWorld {
  server = 'fake/flat'
  #items = {}

  constructor (blocks) {
    this.blocks = blocks.map(block => ({ ...block }))
  }

  async reset (inventory) {
    this.#items = { ...inventory }
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
    const index = action === 'mine' ? this.blocks.findIndex(block => block.block === target) : -1
    if (index < 0) return { ok: false, message: `fake world cannot ${action} ${target}`, output: null, events: [] }
    this.blocks.splice(index, 1)
    this.#items[target] = (this.#items[target] ?? 0) + 1
    return { ok: true, message: `mined ${target}`, output: { block_removed: true, collected: { [target]: 1 } }, events: [] }
  }
}
