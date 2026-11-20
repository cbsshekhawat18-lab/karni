/**
 * The part of the Web Storage API a save layer needs. localStorage,
 * sessionStorage, a portal's data module and the memory fallback all fit it.
 */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  readonly length?: number;
  key?(index: number): string | null;
}
