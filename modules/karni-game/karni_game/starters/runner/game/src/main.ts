// __GAME_TITLE__: a one-tap endless runner on @karni/game. Its rules are a simulation in
// src/rules (@karni/game/sim, moved with @karni/game/collide), its screens are scenes
// (@karni/game/scenes) with the UI kit's panels, settings, pause and touch buttons
// (@karni/game/ui), it draws with @karni/game/draw and makes every sound with
// @karni/game/sfx. The server (karni-game) keeps the player, the save slots, the boards,
// the daily seed, the wallet and the shop: src/session.ts.
import {
    createAudio,
    createInput,
    createStorage,
    createView,
    linkPortal,
    pauseOnHidden,
} from "@karni/game";
import { drawCover } from "@karni/game/scenes";
import { createSimLoop } from "@karni/game/sim";
import {
    applySettings,
    createDevOverlay,
    createSettings,
    createUi,
    guardBoot,
    openSettings,
    showBootFailure,
} from "@karni/game/ui";
import { createArt } from "./art/art";
import { BINDINGS, CONTROLS } from "./controls";
import { GAME, TITLE } from "./game";
import { WORLD, score } from "./rules";
import { createRunControl, type RunControl } from "./run";
import { createGameScenes } from "./scenes";
import { openSession } from "./session";
import { createSounds } from "./sound";

const canvas = document.getElementById("game") as HTMLCanvasElement;
const hud = document.getElementById("hud") as HTMLElement;

void guardBoot(async () => {
    const view = createView({ canvas, width: WORLD.width, height: WORLD.height });
    const input = createInput({ target: canvas, view, bindings: BINDINGS });
    const audio = createAudio({ volumes: { effects: 0.7, music: 0.5 } });
    audio.unlockOn(input);
    const sfx = createSounds(audio);
    const ui = createUi({ input });
    // Settings stay on this device, apart from the game's saves.
    const settings = createSettings({ storage: createStorage({ namespace: `${GAME}-settings` }) });
    applySettings({ store: settings, audio, input, ui });

    // The drawing reads the run and the run draws: the run is made just after.
    let run!: RunControl;
    const art = createArt(canvas, view, {
        state: () => run.state,
        running: () => run.screen === "play",
        best: () => run.session?.progress.best ?? 0,
        label: () => (run.mode === "daily" && run.screen !== "title" ? "Today's run" : ""),
        hat: () => run.session?.wearing("hat") ?? null,
    });
    const follow = (): void => art.settings(settings.state.colourSafe, settings.state.reducedMotion);
    follow();
    settings.subscribe(follow);

    run = createRunControl({
        art,
        sfx,
        jumped: () => {
            const pressed = input.pressed("jump");
            // The jump edge is read by the first step of a frame only.
            input.endFrame();
            return pressed;
        },
        onScreen: (screen) => {
            hud.dataset.screen = screen;
            if (screen === "title" || screen === "play") app.go(screen);
            if (screen === "title") sfx.stopMusic({ fade: 0.6 });
        },
        onOver: (result) => {
            hud.dataset.best = String(result.best);
            app.over(result);
        },
    });

    const hooks = {
        keys: () => {
            if (input.pressed("mute")) settings.set({ muted: !settings.state.muted });
            if (run.screen === "title" && input.pressed("jump") && !ui.modal) run.begin("endless");
        },
        render: (alpha: number) => {
            hud.dataset.score = String(score(run.state));
            art.render(alpha, frameDt);
            drawCover(art.renderer.context, app.cover, canvas.width, canvas.height, "#0b1d33");
        },
        openSettings: () => void openSettings(ui, { store: settings, controls: CONTROLS }),
    };
    let frameDt = 0;
    const loop = createSimLoop({
        target: () => run.recorder,
        input: () => run.input(),
        beforeStep: (dt) => app.update(dt),
        active: () => run.screen === "play" && app.stack.top?.name === "play",
        onEvents: (events) => run.events(events),
        render: (alpha, dt) => {
            frameDt = dt;
            art.update(dt);
            app.draw(alpha);
        },
        afterFrame: () => input.endFrame(),
    });
    const app = createGameScenes({ loop, input, audio, ui, settings, sfx, run }, hooks);
    pauseOnHidden([loop, audio]);
    // A pause menu pauses the loop, and the sound stops with it.
    audio.follow(loop);
    createDevOverlay(ui, { loop, entities: () => run.state.track.islands.length + art.particles.count });
    loop.start();

    const boot = (): void =>
        app.load({
            title: TITLE,
            run: async (report) => {
                const session = await openSession((done, total) => report(done / total));
                run.useSession(session);
                linkPortal(session.portal, { audio, loop, input });
                session.portal.loadingFinished();
                if (session.daily) hud.dataset.daily = session.daily.date;
            },
            onDone: () => run.show("title"),
            onFailed: (error) => {
                const failure = showBootFailure({
                    error,
                    onRetry: () => {
                        failure.destroy();
                        boot();
                    },
                });
            },
        });
    boot();

    if (__KARNI_GAME_DEV__) {
        // A development handle, dropped from every build by the preset's flag.
        (window as unknown as Record<string, unknown>).__game = { loop, run, sfx, settings };
    }
});
