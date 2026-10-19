"""karni-approvals: maker-checker approvals for Karni projects.

A model opts in with ``class Karni: requires_approval = [...]`` (or ``True``).
From then on a change to those fields by anyone — through the API, the admin
or plain code — becomes a :class:`~karni_approvals.models.PendingChange`
holding the diff instead of a write; a second person holding the approve
permission applies or rejects it, with a reason. The maker can never be the
checker, in code. See the README.
"""

from __future__ import annotations
