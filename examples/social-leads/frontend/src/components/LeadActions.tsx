// The detail page's actions: the status picker, Convert (with a deal value)
// and Score. `onChange` lets the page re-read the lead afterwards.
import { Button, Input, Label, Modal, Select } from "@karni/ui";
import { useState } from "react";
import { STATUSES } from "./lead-status";
import { useLeadAction } from "./use-lead-action";

export function LeadActions({ id, status, onChange }: { id: string; status: string; onChange: () => void }) {
    const act = useLeadAction();
    const [open, setOpen] = useState(false);
    const [value, setValue] = useState("");
    const run = async (path: string, body?: Record<string, unknown>, done?: string) => {
        if ((await act(`${id}/${path}/`, body, done)) !== null) onChange();
    };
    return (
        <div className="flex flex-wrap items-center gap-2">
            <Select
                value={status}
                options={STATUSES}
                onValueChange={(next) => next !== null && void run("status", { status: next }, `Status: ${next}`)}
            />
            <Button variant="outline" onClick={() => void run("score-with-ai", {}, "Scored")}>
                Score
            </Button>
            <Modal
                title="Convert lead"
                open={open}
                onOpenChange={setOpen}
                trigger={<Button disabled={status === "converted"}>Convert</Button>}
                footer={
                    <Button
                        onClick={() =>
                            void run("convert", { conversion_value: value || "0" }, "Converted").then(() => setOpen(false))
                        }
                    >
                        Convert
                    </Button>
                }
            >
                <Label htmlFor="conversion-value">Deal value (₹)</Label>
                <Input id="conversion-value" type="number" value={value} onChange={(e) => setValue(e.target.value)} />
            </Modal>
        </div>
    );
}
