// The leaderboard: the best clears of every member, and today's deal. The game API
// answers the boards (karni-game), and a banned or erased member is on none.
import { DataTable, Page, type DataTableColumn } from "@karni/ui";
import type { BoardEntry } from "@karni/game";
import { useBoards } from "../game/useBoards";

const columns: DataTableColumn<BoardEntry>[] = [
    { key: "rank", header: "Rank" },
    { key: "handle", header: "Member", render: (row) => (row.me ? `${row.handle} (you)` : row.handle) },
    { key: "value", header: "Points" },
];

export default function LeaderboardPage() {
    const { boards, error } = useBoards();
    const table = (caption: string, rows: readonly BoardEntry[]) => (
        <section className="grid gap-2">
            <h2 className="text-base font-semibold">{caption}</h2>
            <DataTable
                caption={caption}
                columns={columns}
                rows={rows}
                loading={boards === null && error === null}
                error={error}
                exportFormats={false}
                getRowKey={(row) => `${row.rank}-${row.handle}`}
                emptyLabel="No clears yet."
            />
        </section>
    );
    return (
        <Page title="Leaderboard" description="Tile Match: the best clears of every member.">
            <div className="grid gap-6 lg:grid-cols-2">
                {table("Best clears", boards?.best.entries ?? [])}
                {table("Today's deal", boards?.daily.entries ?? [])}
            </div>
        </Page>
    );
}
