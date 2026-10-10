import { LoginForm, Page } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function LoginPage() {
    const navigate = useNavigate();
    return (
        <Page title="Sign in">
            <LoginForm
                title={null}
                description="Demo logins: attendee@example.com, organizer@example.com or demo@example.com, password karni-password."
                onSuccess={() => void navigate({ to: "/events" })}
            />
        </Page>
    );
}
