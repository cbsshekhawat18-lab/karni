"""An index for the generated-report list's ?status= filter (karni.W967)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("karni_reports", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="generatedreport",
            index=models.Index(fields=["status"], name="karni_reports_by_status"),
        ),
    ]
