import { Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function BooksPage() {
    const navigate = useNavigate();
    return (
        <Page title="Books">
            <ResourceTable
                resource="books"
                onRowClick={(row) =>
                    void navigate({ to: "/books/$id", params: { id: String(row.id) } })
                }
                onEdit={(row) =>
                    void navigate({ to: "/books/$id/edit", params: { id: String(row.id) } })
                }
                onCreate={() => void navigate({ to: "/books/new" })}
            />
        </Page>
    );
}
