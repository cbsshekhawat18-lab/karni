import { Page, ResourceForm } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

export default function BookingFormPage() {
    const { id } = useParams({ strict: false });
    const navigate = useNavigate();
    const picked = new URLSearchParams(window.location.search);
    const defaults =
        id === undefined
            ? { event: picked.get("event"), tier: picked.get("tier"), quantity: 1 }
            : undefined;
    return (
        <Page
            title={id === undefined ? "Book tickets" : "Edit booking"}
            description="Your seats are held until you pay."
        >
            <ResourceForm
                resource="bookings"
                id={id}
                defaultValues={defaults}
                onSuccess={(result) =>
                    void navigate({ to: "/bookings/$id", params: { id: String(result.id) } })
                }
            />
        </Page>
    );
}
