// What the page shows beside the canvas: the player, the wallet and the shop, the
// daily check-in and the ad reward, the board and the achievements, and the way
// for a guest to keep their progress (sign in with a code sent by email).
import { Button, OtpLoginForm, Stat } from "@karni/ui";
import type { ReactNode } from "react";
import { hasAds } from "./session";
import type { GameActions, GameState } from "./useGame";

type Game = GameState & GameActions;

function Panel({ title, children, testId }: { title: string; children: ReactNode; testId: string }) {
    return (
        <section className="rounded-lg border border-border p-4" data-testid={testId}>
            <h2 className="mb-3 text-base font-semibold">{title}</h2>
            {children}
        </section>
    );
}

function Account({ game, signedIn }: { game: Game; signedIn: boolean }) {
    const guest = game.player?.guest !== false;
    return (
        <Panel title={game.player ? game.player.handle : "Player"} testId="player">
            <p className="text-sm" data-testid="player-kind">
                {guest ? "Playing as a guest on this device." : "Playing on your account."}
            </p>
            {guest && !signedIn ? (
                <OtpLoginForm title="Keep your progress" description="Sign in with a code sent to your email: your runs, coins and items stay." />
            ) : null}
        </Panel>
    );
}

function Wallet({ game }: { game: Game }) {
    const coins = game.wallet?.balances.find((balance) => balance.currency === "coins")?.balance ?? 0;
    return (
        <Panel title="Wallet and shop" testId="wallet">
            <Stat label="Coins" value={<span data-testid="balance">{coins}</span>} />
            <ul className="mt-3 space-y-2">
                {game.shop.map((item) => (
                    <li key={item.key} className="flex items-center justify-between gap-2" data-testid={`item-${item.key}`}>
                        <span>
                            {item.title} {item.price ? `(${item.price.amount} ${item.price.currency})` : ""}
                        </span>
                        {!item.owned ? (
                            <Button size="sm" onClick={() => void game.buy(item.key)}>Buy</Button>
                        ) : item.equipped ? (
                            <span className="text-sm">Equipped</span>
                        ) : (
                            <Button size="sm" variant="outline" onClick={() => void game.equip(item.key)}>Equip</Button>
                        )}
                    </li>
                ))}
            </ul>
        </Panel>
    );
}

function Daily({ game }: { game: Game }) {
    const streak = game.daily?.streak;
    return (
        <Panel title="Today" testId="daily">
            <p className="text-sm" data-testid="streak">
                {streak ? `Streak: ${streak.current} day(s)${streak.checked_in ? ", checked in" : ""}` : "No streak yet."}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" disabled={streak?.checked_in === true} onClick={() => void game.checkIn()}>Check in</Button>
                {hasAds ? (
                    <Button size="sm" variant="outline" onClick={() => void game.watchAd()}>Watch an ad for coins</Button>
                ) : null}
                <Button size="sm" variant="outline" disabled={!game.daily?.board} onClick={game.playDaily}>Play the daily run</Button>
            </div>
        </Panel>
    );
}

function Board({ game }: { game: Game }) {
    const entries = game.board?.entries ?? [];
    return (
        <Panel title="High scores" testId="board">
            {entries.length === 0 ? <p className="text-sm">No scores yet.</p> : null}
            <ol className="space-y-1">
                {entries.map((entry) => (
                    <li key={`${entry.rank}-${entry.handle}`} className={entry.me ? "font-semibold" : undefined}>
                        {entry.rank}. {entry.handle}: {entry.value}
                    </li>
                ))}
            </ol>
        </Panel>
    );
}

function Achievements({ game }: { game: Game }) {
    return (
        <Panel title="Achievements" testId="achievements">
            <ul className="space-y-1">
                {game.achievements.map((achievement) => (
                    <li key={achievement.key} data-unlocked={achievement.unlocked_at ? "yes" : "no"}>
                        {achievement.unlocked_at ? "Unlocked: " : ""}
                        {achievement.title} ({Math.min(achievement.progress, achievement.goal)}/{achievement.goal})
                    </li>
                ))}
            </ul>
        </Panel>
    );
}

export function GameHud({ game, signedIn }: { game: Game; signedIn: boolean }) {
    return (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
            <p
                className="text-sm md:col-span-2"
                role="status"
                data-testid="status"
                data-online={game.online ? "yes" : "no"}
                data-runs={game.progress.runs}
            >
                {game.ready ? game.notice || "Tap the game or press Space to play." : "Loading."}
                {game.waiting > 0 ? ` ${game.waiting} change(s) wait for the network.` : ""}
                {` Best: ${game.progress.best}. Runs: ${game.progress.runs}.`}
            </p>
            <Account game={game} signedIn={signedIn} />
            <Wallet game={game} />
            <Daily game={game} />
            <Board game={game} />
            <Achievements game={game} />
        </div>
    );
}
