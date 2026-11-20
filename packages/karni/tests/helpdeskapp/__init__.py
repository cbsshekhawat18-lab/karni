"""A small part of a family project: a help desk's support profiles, tickets and notes.

It adds a profile (``SupportProfile``), rows that point at a person
(``Ticket``, with a copied contact name and email that erase blanks), a
note that points at any record by content type (``Note``, a
``GenericForeignKey`` a merge moves) and the person fact ``open_tickets``.
"""
