import type { Portal } from "./types";

/** Anything with separate mute sources, such as the audio from `createAudio`. */
export interface MuteTarget {
  setMuted(source: "ad" | "portal", muted: boolean): void;
}

/** Anything that pauses for a named reason, such as the loop from `createLoop`. */
export interface PauseTarget {
  pause(reason: string): void;
  resume(reason: string): void;
}

export interface LinkTargets {
  /** Muted during every ad ("ad") and while the portal's own setting says so ("portal"). */
  audio?: MuteTarget & Partial<PauseTarget>;
  /** Paused during every ad ("ad") and when the portal asks ("portal"). */
  loop?: PauseTarget;
  /** Held keys are let go when an ad starts, so nothing stays pressed behind it. */
  input?: { releaseAll(): void };
}

/**
 * Connect a portal's ad and setting events to the game's audio, loop and
 * input. Returns the function that disconnects them. Each target is
 * optional, and a game that wants other behaviour listens to `portal.on`
 * itself instead.
 */
export function linkPortal(portal: Portal, targets: LinkTargets): () => void {
  const { audio, loop, input } = targets;
  audio?.setMuted("portal", portal.muted);
  const off = [
    portal.on("adstart", () => {
      audio?.setMuted("ad", true);
      audio?.pause?.("ad");
      loop?.pause("ad");
      input?.releaseAll();
    }),
    portal.on("adend", () => {
      audio?.setMuted("ad", false);
      audio?.resume?.("ad");
      loop?.resume("ad");
    }),
    portal.on("mute", (muted) => audio?.setMuted("portal", muted)),
    portal.on("pause", (paused) => {
      if (paused) {
        loop?.pause("portal");
        audio?.pause?.("portal");
      } else {
        loop?.resume("portal");
        audio?.resume?.("portal");
      }
    }),
  ];
  return () => {
    for (const unsubscribe of off) unsubscribe();
  };
}
