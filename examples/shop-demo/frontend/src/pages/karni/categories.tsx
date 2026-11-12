// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function CategoriesPage() {
    const navigate = useNavigate();
    return (
        <Page
            title="Categories"
            actions={
                <Button onClick={() => void navigate({ to: "/categories/new" })}>New</Button>
            }
        >
            <ResourceTable
                resource="categories"
                onEdit={(row) =>
                    void navigate({ to: "/categories/$id/edit", params: { id: String(row.id) } })
                }
            />
        </Page>
    );
}
