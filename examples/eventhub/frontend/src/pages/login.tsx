import { Button, Input, Label, Page, useAuth } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";

export default function LoginPage() {
    const { login } = useAuth();
    const navigate = useNavigate();
    const [error, setError] = useState<string | null>(null);

    async function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        const result = await login(String(data.get("email")), String(data.get("password")));
        if ("ok" in result && result.ok) {
            void navigate({ to: "/events" });
        } else {
            setError("That email and password do not match.");
        }
    }

    return (
        <Page
            title="Sign in"
            description="Demo logins: attendee@example.com, organizer@example.com or demo@example.com, password karni-password."
        >
            {/* eslint-disable-next-line karni/no-raw-elements -- @karni/ui ships no login form (FRICTION F4) */}
            <form className="max-w-sm space-y-4" onSubmit={(event) => void submit(event)}>
                <div className="space-y-1">
                    <Label htmlFor="email">Email</Label>
                    <Input id="email" name="email" type="email" autoComplete="email" required />
                </div>
                <div className="space-y-1">
                    <Label htmlFor="password">Password</Label>
                    <Input id="password" name="password" type="password" required />
                </div>
                {error ? <p className="text-sm text-destructive">{error}</p> : null}
                <Button type="submit">Sign in</Button>
            </form>
        </Page>
    );
}
