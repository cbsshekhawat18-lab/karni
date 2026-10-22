/**
 * RuleTester suite for karni/no-style-literals (ESLint 9 under vitest).
 */
import { RuleTester } from "eslint";

import rule from "./rules/no-style-literals.js";

const ruleTester = new RuleTester({
  languageOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});

const literal = { messageId: "literal" };

ruleTester.run("no-style-literals", rule, {
  valid: [
    { code: 'const c = "bg-primary text-primary-foreground hover:bg-primary-hover";' },
    { code: 'const c = "p-4 px-2.5 gap-1.5 max-w-96 min-w-32 h-10 w-full -translate-x-1/2";' },
    { code: 'const c = "rounded-md rounded-t-lg shadow-md font-semibold text-sm leading-none";' },
    { code: 'const c = "z-popover opacity-50 disabled:opacity-50 ring-2 ring-offset-2 border";' },
    { code: 'const c = "w-[var(--radix-popover-trigger-width)] grid-cols-[max-content_1fr]";' },
    { code: 'const c = "data-[state=checked]:bg-primary [&>svg]:h-4 group-data-[x=1]:p-2";' },
    { code: 'const label = "Page 2 of 10";' },
    { code: 'import "./styles.css";' },
    { code: "<div style={{ width: `${percent}%`, left: pct(x, width) }} />" },
    { code: "<div style={{ opacity: 0, flexGrow: value }} />" },
  ],
  invalid: [
    { code: 'const c = "w-[13px]";', errors: [literal] },
    { code: 'const c = "bg-[#fff] p-4";', errors: [literal, literal] },
    { code: 'const c = "text-[hsl(0_0%_10%)]";', errors: [literal] },
    { code: 'const c = "bg-slate-500";', errors: [literal] },
    { code: 'const c = "hover:text-white";', errors: [literal] },
    { code: 'const c = "hover:bg-primary/90";', errors: [literal] },
    { code: 'const c = "border-destructive/50";', errors: [literal] },
    { code: 'const c = "p-13";', errors: [literal] },
    { code: 'const c = "max-w-xs";', errors: [literal] },
    { code: 'const c = "z-50";', errors: [literal] },
    { code: 'const c = "opacity-40";', errors: [literal] },
    { code: 'const c = "duration-300";', errors: [literal] },
    { code: 'const c = "text-4xl";', errors: [literal] },
    { code: 'const c = "shadow-xl";', errors: [literal] },
    { code: 'const c = "border-4";', errors: [literal] },
    { code: 'const c = "ring-4";', errors: [literal] },
    { code: 'const c = cn("rounded-2xl", active && "font-black");', errors: [literal, literal] },
    { code: "const c = `p-4 ${x} m-[3px]`;", errors: [literal] },
    { code: '<div style={{ color: "#333" }} />', errors: [literal] },
    { code: '<div style={{ padding: "12px", margin: 8 }} />', errors: [literal, literal] },
  ],
});
