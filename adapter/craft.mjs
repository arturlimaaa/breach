// The core's generic item names. Every log and every planks variant counts as one item.
export const normalize = name => name.endsWith('_log') ? 'log' : name.endsWith('_planks') ? 'planks' : name

// Window slots for a grid, as [slot, item] pairs. Slot 0 is the result and slot 1 the top-left cell, in the
// inventory's 2x2 grid and a crafting table's 3x3 grid alike. A count map {item: n} fills one item per cell, left to
// right and top to bottom, which only crafts shapeless or full-square recipes. Rows ([[item | null]]) keep a shape.
// Returns null when the grid does not fit `size`.
export function slotsFor (grid, size) {
  let rows = grid
  if (!Array.isArray(grid)) {
    const counts = Object.entries(grid)
    if (!counts.every(([, n]) => Number.isInteger(n) && n > 0)) return null
    const cells = counts.flatMap(([item, n]) => Array(n).fill(item))
    rows = Array.from({ length: Math.ceil(cells.length / size) }, (_, r) => cells.slice(r * size, (r + 1) * size))
  }
  if (rows.length > size || rows.some(row => !Array.isArray(row) || row.length > size)) return null
  return rows.flatMap((row, r) => row.map((item, c) => [1 + r * size + c, item])).filter(([, item]) => item)
}

// Right-clicks one item into each slot. Picking up a stack swaps it with whatever the cursor holds.
export async function place (bot, window, slots) {
  for (const [slot, item] of slots) {
    if (normalize(window.selectedItem?.name ?? '') !== item) {
      const stack = window.items().find(stack => normalize(stack.name) === item)
      if (!stack) throw new Error(`no ${item} left to place`)
      await bot.clickWindow(stack.slot, 0, 0)
    }
    await bot.clickWindow(slot, 1, 0)
  }
  if (window.selectedItem) await bot.putSelectedItemRange(window.inventoryStart, window.inventoryEnd, window, null)
}

// Moves whatever sits in the grid back into the inventory.
export async function clear (bot, window, size) {
  for (let slot = 1; slot <= size * size; slot++) if (window.slots[slot]) await bot.putAway(slot)
}
