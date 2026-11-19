#!/usr/bin/env node
// The karni-game command: build tools of @karni/game (see `karni-game help`).
import { main } from "../dist/cli.js";

process.exitCode = await main(process.argv.slice(2));
