"""An index for the pending-change list's ?action= filter (karni.W967)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("karni_approvals", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="pendingchange",
            index=models.Index(fields=["action"], name="karni_approvals_by_action"),
        ),
    ]
