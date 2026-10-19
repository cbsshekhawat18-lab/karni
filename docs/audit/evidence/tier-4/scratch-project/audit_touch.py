"""audit4: change a Venue from a management command, with and without current_user()."""

from django.core.management.base import BaseCommand
from karni.middleware import current_user

from events.models import Venue


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("pk")
        parser.add_argument("name")
        parser.add_argument("--as-user", default="", help="email of the user to stamp")

    def handle(self, pk, name, as_user, **options):
        venue = Venue.objects.get(pk=pk)
        if as_user:
            from django.contrib.auth import get_user_model

            user = get_user_model().objects.get(email=as_user)
            with current_user(user):
                venue.name = name
                venue.save()
        else:
            venue.name = name
            venue.save()
        venue.refresh_from_db()
        self.stdout.write(
            f"command ({'with' if as_user else 'without'} current_user): name={venue.name!r} "
            f"created_by={getattr(venue.created_by, 'email', None)} "
            f"updated_by={getattr(venue.updated_by, 'email', None)} updated_at={venue.updated_at.isoformat()}"
        )
