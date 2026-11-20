import { Page, ResourceDetail } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

export default function BookDetailPage() {
    const { id } = useParams({ from: "/books/$id" });
    const navigate = useNavigate();
    return (
        <Page title="Book">
            <ResourceDetail
                resource="books"
                id={id}
                onEdit={() => void navigate({ to: "/books/$id/edit", params: { id } })}
            />
        </Page>
    );
}
