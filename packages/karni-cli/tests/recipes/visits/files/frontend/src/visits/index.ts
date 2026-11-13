// The visits part's registration: frontend/src/karni/parts.ts calls it at startup.
export const registered: string[] = [];

export function register(): void {
    registered.push("visits");
}
