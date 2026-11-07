// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function InterventionsPage() {
    const navigate = useNavigate();
    return (
        <Page
            title="Interventions"
            actions={
                <Button onClick={() => void navigate({ to: "/interventions/new" })}>New</Button>
            }
        >
            <ResourceTable
                resource="interventions"
                onEdit={(row) =>
                    void navigate({ to: "/interventions/$id/edit", params: { id: String(row.id) } })
                }
            />
        </Page>
    );
}
