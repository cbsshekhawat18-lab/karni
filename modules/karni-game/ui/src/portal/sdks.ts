/**
 * Where each portal serves its SDK. These are the portals' public script
 * addresses, not ids: a game's own ids come from the project's config. Each
 * is a separate constant so a build keeps only the one its adapter imports.
 * Every adapter and registry row takes another address as an option.
 */
export const POKI_SDK_URL = "https://game-cdn.poki.com/scripts/v2/poki-sdk.js";
export const CRAZYGAMES_SDK_URL = "https://sdk.crazygames.com/crazygames-sdk-v3.js";
export const GAMEDISTRIBUTION_SDK_URL = "https://html5.api.gamedistribution.com/main.min.js";
export const Y8_SDK_URL = "https://cdn.y8.com/minimal-sdk/2-0/y8.min.js";
