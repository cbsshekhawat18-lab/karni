/**
 * Shared MSW server for the whole test suite.
 *
 * vitest.setup.ts wires listen/resetHandlers/close around every test file, so
 * suites only `server.use(...)` for per-test overrides. The simulated backend
 * (handlers, OpenAPI fixture, in-memory DB, auth test controls) lives in
 * ./handlers — import scenario helpers such as `resetMswData` and
 * `authTestControls` from there.
 */
import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);

export {
  authTestControls,
  handlers,
  mswDb,
  openApiFixture,
  openApiFixtureWithAuthMode,
  resetMswData,
  TEST_2FA_USER,
  TEST_CSRF_TOKEN,
  TEST_EPHEMERAL_TOKEN,
  TEST_OTP,
  TEST_USER,
} from "./handlers";
