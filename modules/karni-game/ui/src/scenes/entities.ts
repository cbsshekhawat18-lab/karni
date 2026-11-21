/**
 * An ordered list of a scene's things (the player, enemies, coins, particles)
 * with tags and removal that is safe in the middle of a loop over it.
 */
export interface EntityList<T extends object = object> {
  /** Add an entity at the end, with any tags. Adding it twice only adds the tags. */
  add<E extends T>(entity: E, ...tags: string[]): E;
  /** Remove an entity. True when it was in the list. Safe while `each` runs. */
  remove(entity: T): boolean;
  /** Remove every entity that has the tag. Returns how many went. */
  removeTagged(tag: string): number;
  /** Remove every entity the test accepts. Returns how many went. */
  removeWhere(test: (entity: T) => boolean): number;
  has(entity: T): boolean;
  /** Does the entity carry the tag? */
  tagged(entity: T, tag: string): boolean;
  /** The entities with a tag, in the order they were added. A copy: safe to change the list while reading it. */
  byTag(tag: string): T[];
  /** The number of entities in the list. */
  readonly size: number;
  /**
   * Call `visit` for each entity in order. An entity removed during the loop
   * and not yet visited is skipped. An entity added during the loop waits for
   * the next one.
   */
  each(visit: (entity: T) => void): void;
  /** Like `each`, over the entities with a tag. */
  eachTagged(tag: string, visit: (entity: T) => void): void;
  clear(): void;
  [Symbol.iterator](): Iterator<T>;
}

export function createEntityList<T extends object = object>(): EntityList<T> {
  let items: T[] = [];
  const tags = new Map<T, Set<string>>();
  const removed = new Set<T>();
  let depth = 0;

  const compact = (): void => {
    if (depth > 0 || removed.size === 0) return;
    items = items.filter((entity) => !removed.has(entity));
    removed.clear();
  };
  const live = (entity: T): boolean => tags.has(entity) && !removed.has(entity);

  const list: EntityList<T> = {
    add(entity, ...entityTags) {
      let own = tags.get(entity);
      if (!own) {
        own = new Set();
        tags.set(entity, own);
        // Removed and added again inside one loop: it takes its old slot back.
        if (removed.has(entity)) removed.delete(entity);
        else items.push(entity);
      }
      for (const tag of entityTags) own.add(tag);
      return entity;
    },
    remove(entity) {
      if (!live(entity)) return false;
      tags.delete(entity);
      removed.add(entity);
      compact();
      return true;
    },
    removeTagged(tag) {
      return list.removeWhere((entity) => tags.get(entity)?.has(tag) === true);
    },
    removeWhere(test) {
      let count = 0;
      for (const entity of [...items]) {
        if (live(entity) && test(entity)) {
          list.remove(entity);
          count += 1;
        }
      }
      return count;
    },
    has: live,
    tagged: (entity, tag) => tags.get(entity)?.has(tag) === true,
    byTag: (tag) => items.filter((entity) => live(entity) && tags.get(entity)?.has(tag)),
    get size() {
      return tags.size;
    },
    each(visit) {
      depth += 1;
      try {
        const end = items.length;
        for (let i = 0; i < end; i += 1) {
          const entity = items[i];
          if (entity !== undefined && live(entity)) visit(entity);
        }
      } finally {
        depth -= 1;
        compact();
      }
    },
    eachTagged(tag, visit) {
      list.each((entity) => {
        if (tags.get(entity)?.has(tag)) visit(entity);
      });
    },
    clear() {
      items = [];
      tags.clear();
      removed.clear();
    },
    [Symbol.iterator]() {
      return items.filter(live)[Symbol.iterator]();
    },
  };
  return list;
}
