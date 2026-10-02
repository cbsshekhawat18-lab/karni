"""Fixture app for the performance suites (optimizer, budgets, caching, factories).

Installed so reverse relations resolve; it has no ``viewsets`` module, so the
auto-router and the committed schema snapshot never see it — the tests build
their viewsets locally with ``auto_register = False``.
"""
