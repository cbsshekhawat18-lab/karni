import type { GameClient } from "../client/client";
import type { Portal } from "../portal/types";
import { createPauseReasons } from "../runtime/reasons";

/**
 * The parts of a `Phaser.Game` the adapter touches (Phaser 3). A real game
 * fits as it is; the adapter imports nothing from Phaser.
 */
export interface PhaserGameLike {
  events: {
    on(event: string, listener: () => void): unknown;
    off(event: string, listener: () => void): unknown;
  };
  loop: { sleep(): void; wake(): void };
  sound: { mute: boolean };
  registry: { set(key: string, value: unknown): unknown };
}

export interface PhaserOptions {
  portal?: Portal;
  client?: GameClient;
  /** Pause when the window loses focus too (Phaser pauses on a hidden tab itself). Default true. */
  pauseOnBlur?: boolean;
}

export interface PhaserLink {
  /** Pause Phaser's loop for a reason; it runs again once every reason is lifted. */
  pause(reason: string): void;
  resume(reason: string): void;
  readonly paused: boolean;
  /** Mute sources kept apart: the player's own setting, the ad and the portal's setting. */
  setMuted(source: "player" | "ad" | "portal", muted: boolean): void;
  disconnect(): void;
}

/** The registry keys a scene reads: `this.registry.get(KARNI_REGISTRY.portal)`. */
export const KARNI_REGISTRY = {
  portal: "karni.portal",
  client: "karni.client",
  link: "karni.link",
} as const;

/**
 * Put the portal and the data client inside a Phaser game. Phaser keeps its
 * loop, input, scale and scenes. The adapter puts the services in the
 * game's registry for every scene, sleeps the loop and mutes Phaser's sound
 * during ads and portal pauses, and pauses on blur.
 */
export function connectPhaser(game: PhaserGameLike, options: PhaserOptions = {}): PhaserLink {
  const mutes = new Set<string>();
  const pauses = createPauseReasons(
    () => game.loop.sleep(),
    () => game.loop.wake(),
  );
  const applyMute = (): void => {
    game.sound.mute = mutes.size > 0;
  };
  const link: PhaserLink = {
    pause: (reason) => void pauses.pause(reason),
    resume: (reason) => void pauses.resume(reason),
    get paused() {
      return pauses.paused;
    },
    setMuted(source, muted) {
      if (muted) mutes.add(source);
      else mutes.delete(source);
      applyMute();
    },
    disconnect() {
      for (const unsubscribe of off) unsubscribe();
    },
  };

  const off: (() => void)[] = [];
  if (options.portal) game.registry.set(KARNI_REGISTRY.portal, options.portal);
  if (options.client) game.registry.set(KARNI_REGISTRY.client, options.client);
  game.registry.set(KARNI_REGISTRY.link, link);

  const portal = options.portal;
  if (portal) {
    link.setMuted("portal", portal.muted);
    off.push(
      portal.on("adstart", () => {
        link.setMuted("ad", true);
        link.pause("ad");
      }),
      portal.on("adend", () => {
        link.setMuted("ad", false);
        link.resume("ad");
      }),
      portal.on("mute", (muted) => link.setMuted("portal", muted)),
      portal.on("pause", (paused) => (paused ? link.pause("portal") : link.resume("portal"))),
    );
  }
  if (options.pauseOnBlur ?? true) {
    const onBlur = (): void => link.pause("blur");
    const onFocus = (): void => link.resume("blur");
    game.events.on("blur", onBlur);
    game.events.on("focus", onFocus);
    off.push(
      () => game.events.off("blur", onBlur),
      () => game.events.off("focus", onFocus),
    );
  }
  return link;
}
