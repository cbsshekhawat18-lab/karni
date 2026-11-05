// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function PersonsPage() {
    const navigate = useNavigate();
    return (
        <Page
            title="Persons"
            actions={
                <Button onClick={() => void navigate({ to: "/persons/new" })}>New</Button>
            }
        >
            <ResourceTable
                resource="persons"
                onRowClick={(row) =>
                    void navigate({ to: "/persons/$id", params: { id: String(row.id) } })
                }
                onEdit={(row) =>
                    void navigate({ to: "/persons/$id/edit", params: { id: String(row.id) } })
                }
            />
        </Page>
    );
}
