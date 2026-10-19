"""karni-impersonation: "log in as user" for support, done safely.

An explicit ``impersonate`` permission (never implied by staff status), no
privilege escalation (a target who holds anything the actor lacks cannot be
impersonated), a persistent banner naming both identities with a one-click
exit, a session record, every write attributed to both identities in
``karni.audit``, a hard block on dangerous actions and a maximum session
length. The README carries the threat model.
"""

from __future__ import annotations
