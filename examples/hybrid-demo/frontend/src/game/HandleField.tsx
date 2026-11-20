// The name a member shows on the boards. A new player is "Player" and four digits, so
// no part of an email address is ever on a public board until the member picks a name.
import { Button, Input, Label } from "@karni/ui";
import { useState } from "react";

export function HandleField({ handle, onSave }: { handle: string; onSave: (handle: string) => Promise<void> }) {
    const [value, setValue] = useState("");
    return (
        <div className="mb-4 flex flex-wrap items-end gap-2">
            <div className="grid gap-1">
                <Label htmlFor="handle">Your name on the boards: {handle || "…"}</Label>
                <Input id="handle" value={value} placeholder="A new name" onChange={(event) => setValue(event.target.value)} />
            </div>
            <Button variant="outline" disabled={value.trim().length < 2} onClick={() => void onSave(value.trim()).then(() => setValue(""))}>
                Save name
            </Button>
        </div>
    );
}
