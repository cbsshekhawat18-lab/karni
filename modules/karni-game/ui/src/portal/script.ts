/**
 * Add a `<script>` to the page and resolve when it has loaded. A script with
 * the same id that is already on the page is not added twice.
 */
export function loadScript(
  src: string,
  options: { id?: string; attributes?: Record<string, string> } = {},
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (typeof document === "undefined") {
      reject(new Error("loadScript needs a page (no document)"));
      return;
    }
    const existing = options.id ? document.getElementById(options.id) : null;
    if (existing) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    if (options.id) script.id = options.id;
    for (const [name, value] of Object.entries(options.attributes ?? {})) {
      script.setAttribute(name, value);
    }
    script.addEventListener("load", () => resolve(), { once: true });
    script.addEventListener("error", () => reject(new Error(`${src} did not load`)), {
      once: true,
    });
    (document.head ?? document.documentElement).appendChild(script);
  });
}
