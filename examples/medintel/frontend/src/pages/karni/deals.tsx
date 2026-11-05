// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function DealsPage() {
    const navigate = useNavigate();
    return (
        <Page
            title="Deals"
            actions={
                <Button onClick={() => void navigate({ to: "/deals/new" })}>New</Button>
            }
        >
            <ResourceTable
                resource="deals"
                onRowClick={(row) =>
                    void navigate({ to: "/deals/$id", params: { id: String(row.id) } })
                }
                onEdit={(row) =>
                    void navigate({ to: "/deals/$id/edit", params: { id: String(row.id) } })
                }
            />
        </Page>
    );
}
