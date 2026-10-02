/**
 * RuleTester suite for karni/no-direct-http (ESLint 9 under vitest).
 */
import { RuleTester } from "eslint";

import rule from "./rules/no-direct-http.js";

const ruleTester = new RuleTester({
  languageOptions: { ecmaVersion: "latest", sourceType: "module" },
});

ruleTester.run("no-direct-http", rule, {
  valid: [
    // The generated client directory is the allowed home (default pattern).
    { code: 'await fetch("/events/");', filename: "/app/frontend/src/api/client.ts" },
    {
      code: 'const ws = new WebSocket("wss://x");',
      filename: "/app/frontend/src/api/realtime.ts",
    },
    // Custom allowPatterns.
    {
      code: 'await fetch("/events/");',
      options: [{ allowPatterns: ["**/http/**"] }],
      filename: "/app/frontend/src/http/client.ts",
    },
    // A locally declared fetch is not the global.
    { code: 'const fetch = (url) => client.get(url); await fetch("/x");' },
    { code: 'function go(fetch) { return fetch("/x"); }' },
    // Unrelated names.
    { code: 'await myFetch("/x");' },
    { code: 'import retry from "axios-retry";' },
    { code: "const server = new WebSocketServer();" },
  ],
  invalid: [
    {
      code: 'await fetch("/events/");',
      filename: "/app/frontend/src/pages/Events.tsx",
      errors: [{ messageId: "fetch" }],
    },
    {
      code: 'window.fetch("/events/");',
      errors: [{ messageId: "fetch" }],
    },
    {
      code: 'globalThis.fetch("/events/");',
      errors: [{ messageId: "fetch" }],
    },
    {
      code: "const xhr = new XMLHttpRequest();",
      errors: [{ messageId: "xhr" }],
    },
    {
      code: 'const ws = new WebSocket("wss://x");',
      errors: [{ messageId: "websocket" }],
    },
    {
      code: 'import axios from "axios";',
      errors: [{ messageId: "axios" }],
    },
    {
      code: 'import adapter from "axios/lib/adapters/http";',
      errors: [{ messageId: "axios" }],
    },
    {
      code: 'const axios = await import("axios");',
      errors: [{ messageId: "axios" }],
    },
    {
      code: 'const axios = require("axios");',
      errors: [{ messageId: "axios" }],
    },
    {
      // The carve-out for tests ships in configs.recommended, not in the rule.
      code: 'await fetch("/events/");',
      filename: "/app/frontend/src/pages/Events.test.tsx",
      errors: [{ messageId: "fetch" }],
    },
  ],
});
