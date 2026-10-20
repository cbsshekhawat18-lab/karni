// The pipeline board: one column per status; drag a card to change its status
// (POST /leads/<id>/status/, which also writes the activity timeline).
import { EmptyState, useResourceList } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";
import { useState, type DragEvent } from "react";
import { BOARD, type LeadRow } from "./lead-status";
import { useLeadAction } from "./use-lead-action";

export function LeadKanban() {
    const list = useResourceList<LeadRow>("leads", { pageSize: 100, ordering: "-created_at" });
    const act = useLeadAction();
    const navigate = useNavigate();
    const [dragging, setDragging] = useState<string | null>(null);
    const rows = list.data?.results ?? [];
    if (!list.isLoading && rows.length === 0) {
        return <EmptyState title="No leads yet" description="Captured leads appear here." />;
    }
    async function drop(event: DragEvent<HTMLDivElement>, status: string) {
        event.preventDefault();
        const id = event.dataTransfer.getData("text/plain");
        setDragging(null);
        if (id !== "" && (await act(`${id}/status/`, { status })) !== null) await list.refetch();
    }
    return (
        <div className="grid gap-3 md:grid-cols-5">
            {BOARD.map((column) => {
                const cards = rows.filter((row) => row.status === column.value);
                return (
                    <div
                        key={column.value}
                        onDragOver={(event) => event.preventDefault()}
                        onDrop={(event) => void drop(event, column.value)}
                        className="flex min-h-80 flex-col gap-2 rounded-md border border-border bg-card p-2"
                    >
                        <div className="flex items-center justify-between px-1 text-xs font-medium">
                            <span>{column.label}</span>
                            <span className="text-muted-foreground">{cards.length}</span>
                        </div>
                        {cards.map((lead) => (
                            <article
                                key={lead.id}
                                draggable
                                onDragStart={(event) => {
                                    event.dataTransfer.setData("text/plain", lead.id);
                                    setDragging(lead.id);
                                }}
                                onClick={() => void navigate({ to: "/leads/$id", params: { id: lead.id } })}
                                className={`cursor-grab rounded border border-border bg-background p-2 text-sm ${
                                    dragging === lead.id ? "opacity-50" : ""
                                }`}
                            >
                                <div className="font-medium">{lead.name || lead.phone}</div>
                                <div className="text-xs text-muted-foreground">{lead.phone}</div>
                                {lead.interest ? <div className="mt-1 line-clamp-2 text-xs">{lead.interest}</div> : null}
                                <div className="mt-2 text-xs text-muted-foreground">
                                    ★ {lead.quality_score}
                                    {lead.source_ad_name ? ` · ${lead.source_ad_name}` : ""}
                                </div>
                            </article>
                        ))}
                    </div>
                );
            })}
        </div>
    );
}
