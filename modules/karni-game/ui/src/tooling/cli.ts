import { resolve } from "node:path";
import { checkPackage, checkSource, formatProblems } from "./checks";
import { API_URL_ENV, PortalConfigError, apiHosts, resolveApiUrl } from "./config";
import { packagePortals } from "./package";
import { checkRules, formatImpurities } from "./rules";
import { PORTALS, portalRow } from "./portals";

const USAGE = `karni-game: build tools of @karni/game

  karni-game portals                       list the portal table
  karni-game package [--portal NAME]...    build, check and zip one package per portal
                     [--out DIR] [--root DIR]
                     [--api-url URL] [--allow-host HOST]...
  karni-game check DIR --portal NAME       check a built package
                     [--allow-host HOST]...
  karni-game check-source [DIR]...         look for portal ids typed into the source (default: src scripts)
  karni-game check-rules [DIR]             fail on a clock, Math.random, the page or the network in the rules (default: src/rules)

Portal ids come from the build environment (KARNI_GAME_<PORTAL>_<OPTION>) or karniGame({ config }).
The game API a portal build calls comes from --api-url or KARNI_GAME_API_URL, and its host is allowed.`;

function values(args: readonly string[], flag: string): string[] {
  const found: string[] = [];
  args.forEach((arg, index) => {
    const next = args[index + 1];
    if (arg === flag && next) found.push(next);
    else if (arg.startsWith(`${flag}=`)) found.push(arg.slice(flag.length + 1));
  });
  return found;
}

function positional(args: readonly string[]): string[] {
  return args.filter((arg, index) => !arg.startsWith("--") && !args[index - 1]?.startsWith("--"));
}

/**
 * Run the command line. Returns the exit code. A build that cannot start (a
 * portal's id missing, a bad KARNI_GAME_API_URL) is one line naming what to
 * set, and exit code 1.
 */
export async function main(
  argv: readonly string[],
  out: (line: string) => void = (line) => process.stdout.write(`${line}\n`),
): Promise<number> {
  try {
    return await run(argv, out);
  } catch (error) {
    // By name: the project's Vite config may load its own copy of the class.
    const refused =
      error instanceof PortalConfigError || (error as Error)?.name === "PortalConfigError";
    if (!refused) throw error;
    out(`FAIL ${(error as Error).message}`);
    return 1;
  }
}

async function run(argv: readonly string[], out: (line: string) => void): Promise<number> {
  const [command, ...args] = argv;
  if (command === "portals") {
    for (const row of PORTALS) {
      const needs = row.config.length ? ` needs ${row.config.join(", ")}` : "";
      out(`${row.name.padEnd(18)} ${row.title}${needs}${row.zip ? ", zipped" : ""}`);
    }
    return 0;
  }
  if (command === "package") {
    const portals = values(args, "--portal");
    const reports = await packagePortals({
      root: values(args, "--root")[0],
      outDir: values(args, "--out")[0],
      portals: portals.length ? portals : undefined,
      apiUrl: values(args, "--api-url")[0],
      check: { allowHosts: values(args, "--allow-host") },
    });
    let failed = false;
    for (const report of reports) {
      if (report.problems.length) {
        failed = true;
        out(
          `FAIL ${report.portal}: ${report.problems.length} problem(s)\n${formatProblems(report.problems)}`,
        );
      } else {
        out(
          `ok   ${report.portal}: ${report.bytes} bytes${report.zip ? `, ${report.zip}` : `, ${report.dir}`}`,
        );
      }
    }
    return failed ? 1 : 0;
  }
  if (command === "check") {
    const [dir] = positional(args);
    const portal = values(args, "--portal")[0];
    if (!dir || !portal) {
      out(USAGE);
      return 2;
    }
    const allowHosts = [
      ...values(args, "--allow-host"),
      ...apiHosts(resolveApiUrl(undefined, process.env)),
    ];
    const problems = checkPackage(resolve(dir), portalRow(portal), { allowHosts });
    out(problems.length ? `FAIL ${portal}\n${formatProblems(problems)}` : `ok   ${portal}`);
    return problems.length ? 1 : 0;
  }
  if (command === "check-source") {
    const dirs = positional(args);
    const env = process.env;
    const ids = Object.entries(env)
      .filter(
        ([name, value]) =>
          name.startsWith("KARNI_GAME_") &&
          name !== "KARNI_GAME_PORTAL" &&
          name !== API_URL_ENV &&
          value,
      )
      .map(([, value]) => value as string);
    const problems = checkSource(
      (dirs.length ? dirs : ["src", "scripts"]).map((dir) => resolve(dir)),
      { ids },
    );
    out(problems.length ? `FAIL\n${formatProblems(problems)}` : "ok   no portal id in the source");
    return problems.length ? 1 : 0;
  }
  if (command === "check-rules") {
    const [dir] = positional(args);
    const problems = checkRules(dir ?? "src/rules");
    out(problems.length ? `FAIL\n${formatImpurities(problems)}` : "ok   the rules are pure");
    return problems.length ? 1 : 0;
  }
  out(USAGE);
  return command === undefined || command === "help" || command === "--help" ? 0 : 2;
}
