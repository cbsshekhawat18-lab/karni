import { LoginForm, Page } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function LoginPage() {
    const navigate = useNavigate();
    return (
        <Page title="Sign in">
            <LoginForm onSuccess={() => void navigate({ to: "/" })} />
        </Page>
    );
}
