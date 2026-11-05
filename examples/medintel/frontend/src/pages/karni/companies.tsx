// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function CompaniesPage() {
    const navigate = useNavigate();
    return (
        <Page
            title="Companies"
            actions={
                <Button onClick={() => void navigate({ to: "/companies/new" })}>New</Button>
            }
        >
            <ResourceTable
                resource="companies"
                onRowClick={(row) =>
                    void navigate({ to: "/companies/$id", params: { id: String(row.id) } })
                }
                onEdit={(row) =>
                    void navigate({ to: "/companies/$id/edit", params: { id: String(row.id) } })
                }
            />
        </Page>
    );
}
