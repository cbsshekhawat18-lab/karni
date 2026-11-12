// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function OrdersPage() {
    const navigate = useNavigate();
    return (
        <Page title="Orders">
            <ResourceTable
                resource="orders"
                onRowClick={(row) =>
                    void navigate({ to: "/orders/$id", params: { id: String(row.id) } })
                }
            />
        </Page>
    );
}
