import { Page, ResourceForm } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

export default function BookFormPage() {
    const { id } = useParams({ strict: false });
    const navigate = useNavigate();
    return (
        <Page title={id === undefined ? "New book" : "Edit book"}>
            <ResourceForm
                resource="books"
                id={id}
                onSuccess={(result) =>
                    void navigate({ to: "/books/$id", params: { id: String(result.id) } })
                }
            />
        </Page>
    );
}
