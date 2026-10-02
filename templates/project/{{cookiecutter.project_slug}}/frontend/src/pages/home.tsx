import { useEffect, useState } from "react";
import { fetchHealth, type Health } from "../api/health";

export default function HomePage() {
    const [health, setHealth] = useState<Health | "checking">("checking");

    useEffect(() => {
        void fetchHealth().then(setHealth);
    }, []);

    return (
        <main>
            <h1>{{ cookiecutter.project_name }}</h1>
            <p>
                Vite + React dev server is running. API requests to{" "}
                <code>/api</code> and <code>/health</code> are proxied to
                Django.
            </p>
            <p>
                Backend readiness: <code>{health}</code>
            </p>
            <p>
                <a href="/api/docs/">API docs</a>
            </p>
        </main>
    );
}
