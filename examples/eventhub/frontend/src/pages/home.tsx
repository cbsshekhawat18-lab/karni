import { Page } from "@karni/ui";
import { useEffect, useState } from "react";
import { fetchHealth, type Health } from "../api/health";

export default function HomePage() {
    const [health, setHealth] = useState<Health | "checking">("checking");

    useEffect(() => {
        void fetchHealth().then(setHealth);
    }, []);

    return (
        <Page
            title="EventHub"
            description="Vite + React dev server. Requests to /api and /health are proxied to Django."
        >
            <p className="text-sm">
                Backend readiness:{" "}
                <code className="rounded bg-muted px-1.5 py-0.5">{health}</code>
            </p>
            <p className="text-sm">
                <a className="font-medium underline underline-offset-4" href="/api/docs/">
                    API docs
                </a>
            </p>
        </Page>
    );
}
