// The page that hosts the game: the canvas and what the player has. Guests play
// without an account and keep their progress when they sign in. The game's code is
// in ../game: the rules, the canvas, the session with the server and this hook.
import { Page, useAuth } from "@karni/ui";
import { useRef } from "react";
import { GameHud } from "../game/Hud";
import { useGame } from "../game/useGame";

export default function GamePage() {
    const canvas = useRef<HTMLCanvasElement | null>(null);
    const signedIn = useAuth().user !== null;
    const game = useGame(canvas, signedIn);
    return (
        <Page title="__GAME_TITLE__" description="Tap or press Space to jump. Coins are worth 10 points.">
            <div className="aspect-video w-full overflow-hidden rounded-lg bg-black">
                <canvas ref={canvas} className="block touch-none" data-testid="game-canvas" />
            </div>
            <GameHud game={game} signedIn={signedIn} />
        </Page>
    );
}
