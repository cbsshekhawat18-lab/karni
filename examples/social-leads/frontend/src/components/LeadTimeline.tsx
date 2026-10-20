// The lead's activity timeline (notes, calls, status changes, assignments),
// newest first, with "add a note" on top.
import { Button, EmptyState, Textarea, useResourceList } from "@karni/ui";
import { useState } from "react";
import { useLeadAction } from "./use-lead-action";

interface Activity {
    id: string;
    activity_type: string;
    content: string;
    created_at: string;
}

export function LeadTimeline({ leadId }: { leadId: string }) {
    const list = useResourceList<Activity>("lead-activities", { filters: { lead: leadId }, pageSize: 100 });
    const act = useLeadAction();
    const [draft, setDraft] = useState("");
    async function addNote() {
        if ((await act(`${leadId}/activity/`, { activity_type: "note", content: draft }, "Note added")) !== null) {
            setDraft("");
            await list.refetch();
        }
    }
    const rows = list.data?.results ?? [];
    return (
        <section className="flex flex-col gap-3">
            <h2 className="text-base font-semibold">Activity</h2>
            <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Add a note for your team" />
            <Button className="self-end" disabled={draft.trim() === ""} onClick={() => void addNote()}>
                Add note
            </Button>
            {rows.length === 0 && !list.isLoading ? <EmptyState title="No activity yet" /> : null}
            <ol className="flex flex-col gap-2">
                {rows.map((row) => (
                    <li key={row.id} className="rounded-md border border-border p-3 text-sm">
                        <div className="flex justify-between text-xs text-muted-foreground">
                            <span>{row.activity_type.replace("_", " ")}</span>
                            <span>{new Date(row.created_at).toLocaleString()}</span>
                        </div>
                        {row.content ? <p className="mt-1 whitespace-pre-wrap">{row.content}</p> : null}
                    </li>
                ))}
            </ol>
        </section>
    );
}
