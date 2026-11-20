// The rules of Tile Match, with no page: a deal of eight pairs shuffled from a seed, a
// move turns two tiles, a pair stays open. The deal's seed and its log of moves are the
// run a score carries, so the server keeps what a member played.
import { createRng } from "@karni/game";

const SYMBOLS = ["◆", "●", "▲", "■", "★", "✚", "☾", "♣"];

export interface Deal {
    seed: number;
    tiles: string[];
    open: boolean[];
    /** The one or two tiles turned now. */
    turned: number[];
    moves: number;
    /** Each move: its number and the two tiles, "3,12". */
    log: [number, string][];
}

export function deal(seed: number): Deal {
    const tiles = createRng(seed).shuffle([...SYMBOLS, ...SYMBOLS]);
    return { seed, tiles, open: tiles.map(() => false), turned: [], moves: 0, log: [] };
}

/** Turn a tile. A third tile turns the last two back unless they matched. */
export function turn(current: Deal, index: number): Deal {
    if (current.open[index] || current.turned.includes(index)) return current;
    const next = { ...current, open: [...current.open], log: [...current.log] };
    next.turned = current.turned.length === 2 ? [index] : [...current.turned, index];
    if (next.turned.length === 2) {
        const [a = 0, b = 0] = next.turned;
        next.moves += 1;
        next.log.push([next.moves, `${a},${b}`]);
        if (next.tiles[a] === next.tiles[b]) {
            next.open[a] = true;
            next.open[b] = true;
            next.turned = [];
        }
    }
    return next;
}

export const cleared = (current: Deal): boolean => current.open.every(Boolean);

/** 1000 for a perfect clear (eight moves), 25 less for each extra move. */
export const score = (current: Deal): number => Math.max(0, 1000 - Math.max(0, current.moves - 8) * 25);
