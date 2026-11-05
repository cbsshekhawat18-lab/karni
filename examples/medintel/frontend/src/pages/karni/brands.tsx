// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function BrandsPage() {
    const navigate = useNavigate();
    return (
        <Page
            title="Brands"
            actions={
                <Button onClick={() => void navigate({ to: "/brands/new" })}>New</Button>
            }
        >
            <ResourceTable
                resource="brands"
                onRowClick={(row) =>
                    void navigate({ to: "/brands/$id", params: { id: String(row.id) } })
                }
                onEdit={(row) =>
                    void navigate({ to: "/brands/$id/edit", params: { id: String(row.id) } })
                }
            />
        </Page>
    );
}
