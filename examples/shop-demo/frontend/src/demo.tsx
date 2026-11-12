// The demo login above the sign-in prompt. The page Django serves carries it in
// three meta tags while DEMO_MODE is on (demo/views.py). It wraps Karni's own
// prompt (defaultAuthGuardSlots.Anonymous), so the form is Karni's, and without
// the tags (the dev server, DEMO_MODE off) the prompt is Karni's alone.
import { defaultAuthGuardSlots, type AuthGuardAnonymousProps } from "@karni/ui";

export interface DemoLogin {
    email: string;
    password: string;
    resetHours: string;
    adminUrl: string | null;
}

function meta(name: string): string | null {
    return document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content ?? null;
}

/** The demo login the page carries, or null when it carries none. */
export function demoLogin(): DemoLogin | null {
    const email = meta("demo-login-email");
    const password = meta("demo-login-password");
    if (email === null || password === null) return null;
    return {
        email,
        password,
        resetHours: meta("demo-reset-hours") ?? "24",
        adminUrl: meta("demo-admin-url"),
    };
}

const KarniSignInPrompt = defaultAuthGuardSlots.Anonymous;

/** AuthGuard's Anonymous slot: the demo login, then Karni's sign-in prompt. */
export function DemoSignInPrompt(props: AuthGuardAnonymousProps) {
    const login = demoLogin();
    return (
        <div className="mx-auto w-full max-w-96 space-y-4">
            {login !== null ? (
                <p
                    data-demo-login=""
                    className="rounded-lg border border-border bg-card p-4 text-sm text-card-foreground"
                >
                    This is a demo. Sign in as <strong>{login.email}</strong> with the password{" "}
                    <strong>{login.password}</strong>, here or in the{" "}
                    {login.adminUrl !== null ? (
                        <a className="underline" href={login.adminUrl}>
                            admin
                        </a>
                    ) : (
                        "admin"
                    )}
                    . Only this account can change data, and the data goes back to the start
                    every {login.resetHours} hours.
                </p>
            ) : null}
            <KarniSignInPrompt {...props} />
        </div>
    );
}
