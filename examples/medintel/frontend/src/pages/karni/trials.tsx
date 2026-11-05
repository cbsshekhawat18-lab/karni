// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function TrialsPage() {
    const navigate = useNavigate();
    return (
        <Page
            title="Trials"
            actions={
                <Button onClick={() => void navigate({ to: "/trials/new" })}>New</Button>
            }
        >
            <ResourceTable
                resource="trials"
                onRowClick={(row) =>
                    void navigate({ to: "/trials/$id", params: { id: String(row.id) } })
                }
                onEdit={(row) =>
                    void navigate({ to: "/trials/$id/edit", params: { id: String(row.id) } })
                }
            />
        </Page>
    );
}
