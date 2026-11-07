// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function ConditionsPage() {
    const navigate = useNavigate();
    return (
        <Page
            title="Conditions"
            actions={
                <Button onClick={() => void navigate({ to: "/conditions/new" })}>New</Button>
            }
        >
            <ResourceTable
                resource="conditions"
                onEdit={(row) =>
                    void navigate({ to: "/conditions/$id/edit", params: { id: String(row.id) } })
                }
            />
        </Page>
    );
}
