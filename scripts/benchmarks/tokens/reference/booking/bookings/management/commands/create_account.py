"""``manage.py create_account EMAIL PASSWORD ROLE``: an account with one role, made or updated."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from karni.accounts.permissions import assign_role, remove_role, user_roles


class Command(BaseCommand):
    help = "Create an account with a role, or set the password and role of an existing one."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("password")
        parser.add_argument("role")

    def handle(self, *args, **options):
        user, _ = get_user_model().objects.get_or_create(email=options["email"].lower())
        user.set_password(options["password"])
        user.is_active = True
        user.email_verified = True
        user.save()
        # Staff also hold the payments module's own role, which lets them see every payment.
        wanted = {options["role"], *(["payments-admin"] if options["role"] == "staff" else [])}
        for slug in set(user_roles(user)) - wanted:
            remove_role(user, slug)
        for slug in wanted:
            assign_role(user, slug)
