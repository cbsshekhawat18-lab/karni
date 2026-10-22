"""``karni ui detect``: adopt a project's design system as Karni's ``--karni-*`` tokens.

The command inspects a frontend and maps what it finds onto the tokens every
@karni/ui component reads (``@karni/ui/styles.css``), in this order:

1. shadcn/ui (``components.json``): Karni's tokens reference the project's
   own CSS variables (:mod:`.shadcn`), and a ``karni-primitives.tsx`` registers
   the project's shadcn components as Karni's primitives (:mod:`.primitives`);
2. a Tailwind theme: ``@theme`` blocks (Tailwind 4) or the evaluated
   ``tailwind.config`` (Tailwind 3, or 4 through ``@config``) (:mod:`.tailwind`);
3. a Material UI, Chakra UI or Mantine theme, read statically from the source
   (:mod:`.designsystems`);
4. nothing: Karni's defaults, listed in one file to edit (:mod:`.defaults`).

Everything lands in one file the project owns, ``karni-theme.css``
(:mod:`.render`). Every value that is not mapped is reported with the reason;
nothing is approximated silently.

Escape hatches: ``--source`` picks the source instead of the detection order,
``--output`` the file's place, ``--no-primitives`` skips the registry, and
both generated files are the project's to edit (a re-run keeps edits unless
``--force``).
"""
