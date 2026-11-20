// Tile Match inside the app: a member plays as their account. The rules are in
// ../game/tiles.ts, the calls to the game API in ../game/useTileMatch.ts.
import { Button, Page } from "@karni/ui";
import { HandleField } from "../game/HandleField";
import { TileGrid } from "../game/TileGrid";
import { useTileMatch } from "../game/useTileMatch";

export default function PlayPage() {
    const game = useTileMatch();
    const actions = (
        <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={game.newDeal}>New deal</Button>
            <Button onClick={game.dailyDeal} disabled={game.daily?.board == null}>Today's deal</Button>
        </div>
    );
    return (
        <Page title="Tile Match" description="Find the eight pairs in as few moves as you can." actions={actions}>
            <p className="mb-4 text-sm" role="status" data-testid="notice" data-board={game.board}>
                {game.notice} Moves: {game.current.moves}.
            </p>
            <HandleField handle={game.handle} onSave={game.rename} />
            <TileGrid current={game.current} onTurn={game.turn} />
            <ul className="mt-6 space-y-1 text-sm" data-testid="achievements">
                {game.achievements.map((row) => (
                    <li key={row.key} data-unlocked={row.unlocked_at ? "yes" : "no"}>
                        {row.unlocked_at ? "Unlocked: " : ""}
                        {row.title} ({Math.min(row.progress, row.goal)}/{row.goal})
                    </li>
                ))}
            </ul>
        </Page>
    );
}
