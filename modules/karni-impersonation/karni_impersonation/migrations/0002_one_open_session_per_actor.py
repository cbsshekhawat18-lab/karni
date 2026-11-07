from django.db import migrations, models
from django.utils import timezone


def close_duplicates(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Keep each actor's newest open session; end the older ones before the constraint."""
    Session = apps.get_model("karni_impersonation", "ImpersonationSession")
    seen = set()
    for row in Session.objects.filter(ended_at__isnull=True).order_by("-started_at"):
        if row.actor_id in seen:
            row.ended_at = timezone.now()
            row.end_reason = "swept"
            row.save(update_fields=["ended_at", "end_reason"])
        seen.add(row.actor_id)


class Migration(migrations.Migration):
    dependencies = [
        ("karni_impersonation", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(close_duplicates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="impersonationsession",
            constraint=models.UniqueConstraint(
                condition=models.Q(("ended_at__isnull", True)),
                fields=("actor",),
                name="karni_impersonation_one_open_per_actor",
            ),
        ),
    ]
