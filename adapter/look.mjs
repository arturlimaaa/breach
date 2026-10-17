import { normalize } from './craft.mjs'

// The grid's look (breach/world.py): eight headings, a corridor 7 wide and 48 steps long, searched step by step with
// the center lane first.
// A diagonal step is one block on each axis, as in the grid; a heading move counts its blocks the same way.
export const HEADINGS = new Map([['N', [0, -1]], ['NE', [1, -1]], ['E', [1, 0]], ['SE', [1, 1]], ['S', [0, 1]], ['SW', [-1, 1]], ['W', [-1, 0]], ['NW', [-1, -1]]])
const LANES = [0, -1, 1, -2, 2, -3, 3]
const LENGTH = 48
// The grid is flat and the world is not, so each corridor cell is a column searched within 16 of the feet, nearest first.
const LEVELS = [0, ...Array.from({ length: 16 }, (_, i) => [i + 1, -i - 1]).flat()]
const KNOWN = new Set(['log', 'stone', 'coal_ore', 'crafting_table'])
const FACES = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]

// What counts as seen, for look and the observation alike: a block that touches air. Worldgen fills caves with
// cave_air, so buried stone and cave walls stay out.
export const touchesAir = (nameAt, x, y, z) => FACES.some(([fx, fy, fz]) => nameAt(x + fx, y + fy, z + fz) === 'air')

// Per heading, the nearest known block as {block, distance}; headings that show none are left out. `nameAt(x, y, z)`
// gives a block name, or null where no chunk is loaded. A block counts only when it touches air: worldgen fills caves
// with cave_air, so buried stone and cave walls stay out.
export function glance (nameAt, x0, y0, z0) {
  const seen = {}
  for (const [heading, [dx, dz]] of HEADINGS) {
    const nearest = scan(nameAt, x0, y0, z0, dx, dz)
    if (nearest) seen[heading] = nearest
  }
  return seen
}

function scan (nameAt, x0, y0, z0, dx, dz) {
  // The width runs along x except east and west, so a diagonal corridor is sheared and has no holes.
  const [wx, wz] = dz === 0 ? [0, 1] : [1, 0]
  for (let k = 1; k <= LENGTH; k++) {
    for (const j of LANES) {
      const x = x0 + k * dx + j * wx
      const z = z0 + k * dz + j * wz
      for (const dy of LEVELS) {
        const y = y0 + dy
        const block = normalize(nameAt(x, y, z) ?? '')
        if (KNOWN.has(block) && touchesAir(nameAt, x, y, z)) return { block, distance: k }
      }
    }
  }
  return null
}
