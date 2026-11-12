// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function ProductsPage() {
    const navigate = useNavigate();
    return (
        <Page
            title="Products"
            actions={
                <Button onClick={() => void navigate({ to: "/products/new" })}>New</Button>
            }
        >
            <ResourceTable
                resource="products"
                onRowClick={(row) =>
                    void navigate({ to: "/products/$id", params: { id: String(row.id) } })
                }
                onEdit={(row) =>
                    void navigate({ to: "/products/$id/edit", params: { id: String(row.id) } })
                }
            />
        </Page>
    );
}
