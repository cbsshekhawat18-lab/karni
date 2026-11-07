import { OtpLoginForm, Page, SocialButton } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";
import { getGoogleIdToken } from "../google";

/** Sign in with a code sent by email, or with a Google ID token. No password. */
export default function LoginPage() {
    const navigate = useNavigate();
    const done = () => void navigate({ to: "/" });
    return (
        <Page title="Sign in">
            <OtpLoginForm onSuccess={done} />
            <SocialButton provider="google" getIdToken={getGoogleIdToken} onSuccess={done} />
        </Page>
    );
}
