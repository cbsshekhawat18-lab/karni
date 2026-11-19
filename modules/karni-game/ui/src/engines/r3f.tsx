import { addAfterEffect, useFrame, useThree } from "@react-three/fiber";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { GameAudio } from "../audio/audio";
import type { GameClient } from "../client/client";
import type { Input } from "../input/input";
import type { AdKind, Portal, PortalStatus } from "../portal/types";
import { createFixedStep, type FixedStep } from "../runtime/fixed-step";
import { pauseOnHidden } from "../runtime/pause";
import { createPauseReasons } from "../runtime/reasons";

/** The game's services, for every component under `KarniGameProvider`. */
export interface KarniGameServices {
  client?: GameClient;
  portal?: Portal;
  audio?: GameAudio;
  input?: Input;
}

const Services = createContext<KarniGameServices>({});

export function KarniGameProvider(props: {
  value: KarniGameServices;
  children?: ReactNode;
}): ReactNode {
  return <Services.Provider value={props.value}>{props.children}</Services.Provider>;
}

export function useKarniGame(): KarniGameServices {
  return useContext(Services);
}

export interface FixedStepHookOptions {
  /** Seconds per step. Default 1/60. */
  step?: number;
  maxSteps?: number;
  /** The longest frame time, in seconds. Default 0.05. */
  maxDt?: number;
}

/**
 * Run `update` in fixed steps inside React Three Fiber's frame loop, with
 * the step cap. Returns the accumulator, whose leftover a render may read.
 */
export function useFixedStep(
  update: (dt: number) => void,
  options: FixedStepHookOptions = {},
): FixedStep {
  const { step, maxSteps } = options;
  const fixed = useMemo(() => createFixedStep({ step, maxSteps }), [step, maxSteps]);
  const latest = useRef(update);
  latest.current = update;
  const maxDt = options.maxDt ?? 0.05;
  useFrame((_state, delta) => {
    fixed.advance(Math.min(delta, maxDt), (dt) => latest.current(dt));
  });
  return fixed;
}

/** Clear the input's edge flags after every rendered frame. */
export function useEndInputFrame(input?: Input): void {
  const fromContext = useKarniGame().input;
  const target = input ?? fromContext;
  useEffect(() => {
    if (!target) return undefined;
    return addAfterEffect(() => target.endFrame());
  }, [target]);
}

export interface GamePause {
  readonly paused: boolean;
  pause(reason: string): void;
  resume(reason: string): void;
}

export interface GamePauseOptions {
  portal?: Portal;
  /** Pause on a hidden tab and on blur. Default true. */
  pauseOnHidden?: boolean;
}

/**
 * Stop the Canvas's frame loop (`frameloop: "never"`) for a hidden tab,
 * blur, ads and portal pauses, each a reason of its own, and start it
 * again when every reason is lifted.
 */
export function useGamePause(options: GamePauseOptions = {}): GamePause {
  const setFrameloop = useThree((state) => state.setFrameloop);
  const fromContext = useKarniGame().portal;
  const portal = options.portal ?? fromContext;
  const [paused, setPaused] = useState(false);
  const reasons = useMemo(
    () =>
      createPauseReasons(
        () => {
          setFrameloop("never");
          setPaused(true);
        },
        () => {
          setFrameloop("always");
          setPaused(false);
        },
      ),
    [setFrameloop],
  );
  const pause = useCallback((reason: string) => void reasons.pause(reason), [reasons]);
  const resume = useCallback((reason: string) => void reasons.resume(reason), [reasons]);
  const watchHidden = options.pauseOnHidden ?? true;
  useEffect(() => {
    if (!watchHidden) return undefined;
    return pauseOnHidden({ pause, resume });
  }, [watchHidden, pause, resume]);
  useEffect(() => {
    if (!portal) return undefined;
    const off = [
      portal.on("adstart", () => pause("ad")),
      portal.on("adend", () => resume("ad")),
      portal.on("pause", (value) => (value ? pause("portal") : resume("portal"))),
    ];
    return () => {
      for (const unsubscribe of off) unsubscribe();
    };
  }, [portal, pause, resume]);
  return { paused, pause, resume };
}

export interface PortalState {
  status: PortalStatus;
  adPlaying: AdKind | null;
  muted: boolean;
}

const IDLE: PortalState = { status: "idle", adPlaying: null, muted: false };

/** The portal's status, the ad playing and its mute setting, as React state. */
export function usePortalState(portal?: Portal): PortalState {
  const fromContext = useKarniGame().portal;
  const target = portal ?? fromContext;
  const last = useRef<PortalState>(IDLE);
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (!target) return () => undefined;
      const off = [
        target.on("ready", onChange),
        target.on("adstart", onChange),
        target.on("adend", onChange),
        target.on("mute", onChange),
      ];
      return () => {
        for (const unsubscribe of off) unsubscribe();
      };
    },
    [target],
  );
  const snapshot = useCallback((): PortalState => {
    if (!target) return IDLE;
    const next = { status: target.status, adPlaying: target.adPlaying, muted: target.muted };
    const prev = last.current;
    if (
      prev.status === next.status &&
      prev.adPlaying === next.adPlaying &&
      prev.muted === next.muted
    ) {
      return prev;
    }
    last.current = next;
    return next;
  }, [target]);
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
