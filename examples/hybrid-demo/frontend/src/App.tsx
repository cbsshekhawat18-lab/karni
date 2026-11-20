import { AuthProvider, KarniProvider, ThemeProvider, Toaster, createKarniClient } from "@karni/ui";
import { RouterProvider } from "@tanstack/react-router";
import { router } from "./routes";

// One client for the whole app: every @karni/ui hook and component reaches
// the Django API through it (same origin; the Vite dev server proxies /api).
const client = createKarniClient({ baseUrl: "/api" });

export default function App() {
    return (
        // Light, dark or the system's choice; <ThemeToggle /> in the layout picks.
        <ThemeProvider>
            <KarniProvider client={client}>
                <AuthProvider>
                    <RouterProvider router={router} />
                    <Toaster />
                </AuthProvider>
            </KarniProvider>
        </ThemeProvider>
    );
}
