# Security policy

## Reporting a vulnerability

**Do not open a public issue, pull request or discussion for a security
problem.**

Report it privately through GitHub's private vulnerability reporting: open the
repository's **Security** tab and choose **Report a vulnerability**. If you
cannot use GitHub, email the maintainer at cbsshekhawat18@gmail.com with
"SECURITY" in the subject.

Include as much of this as you can:

- the affected package (`karni`, `karni-cli`, `@karni/ui`, a module such as
  `karni-payments`, or the project scaffold) and version;
- what an attacker can do, and what they need first (an account, a role, a
  particular setting);
- steps to reproduce: ideally a minimal model, viewset or `access`
  declaration, and the request that goes wrong;
- any fix you have in mind.

## What happens next

| Step | Target |
|---|---|
| Acknowledge your report | within 3 working days |
| Confirm or rule out the issue, with a severity | within 10 working days |
| Release a fix | as soon as practical; we agree the date with you |
| Publish an advisory (GitHub Security Advisory, plus a CVE where it applies) | when the fix is released |

We ask you to keep the issue private until the fix ships, and for no longer
than 90 days from your report unless we agree otherwise together. We credit
reporters in the advisory unless you ask us not to.

## Supported versions

Karni is in 0.x. Security fixes go into the **latest minor release** only.
Upgrade with `karni upgrade`; every breaking change between releases is
recorded and, where it can be, applied for you.

From 1.0 onwards, fixes go into the latest minor of the current major and of
the previous major for six months after a new major ships.

## What counts as a Karni vulnerability

Karni enforces security-relevant behaviour on behalf of every project built on
it, so a flaw in these areas affects all of them. We treat these as
vulnerabilities:

- **Access enforcement.** A row visible or writable outside its `access`
  declaration. That includes leaks through `?expand=`, nested serializers,
  filters, search, ordering, pagination counts, caching or the admin.
- **Soft delete and scopes.** Deleted or out-of-scope rows reachable through a
  default manager, a relation or an API response.
- **Authentication.** Flaws in `karni.accounts`: tokens, refresh and
  revocation, password reset, email verification, 2FA, session handling.
- **Modules.** For example, accepting a payment webhook without verifying its
  signature in `karni-payments`.
- **Insecure defaults.** Settings the scaffold generates for production that
  are insecure (debug, hosts, cookies, headers, secrets), and generated code
  that leaves a resource unprotected.
- **`karni` CLI.** Commands that execute or overwrite more than they say they
  do. That includes `karni upgrade` codemods writing outside the project.

Not in scope: vulnerabilities in your own project's code, unless Karni's
documented behaviour led you there (then we want to hear about it: it is a
documentation or design problem); and issues in third-party dependencies,
which you should report upstream. Do tell us if Karni's pinned range keeps you
on a vulnerable version.

## What Karni enforces by default

The security baseline a project gets without configuration — access
enforcement, authentication, throttling, headers, logging and supply-chain
scanning — is documented at
<https://cbsshekhawat18-lab.github.io/karni/security/#what-karni-does-by-default>
(`docs/security.md` in this repository).
