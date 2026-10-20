// The table's bulk actions: move every selected lead to one status.
import type { BulkAction } from "@karni/ui";
import { BOARD } from "./lead-status";
import { useLeadAction } from "./use-lead-action";

export function useBulkStatus(onDone: () => void): BulkAction[] {
    const act = useLeadAction();
    return BOARD.map((status) => ({
        label: `Mark ${status.label.toLowerCase()}`,
        onClick: (ids: string[]) =>
            void Promise.all(ids.map((id) => act(`${id}/status/`, { status: status.value }))).then(onDone),
    }));
}
