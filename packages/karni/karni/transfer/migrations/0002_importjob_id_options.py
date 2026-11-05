"""The id options of an import job: match rows by the id column, keep the file's ids."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("karni_transfer", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="importjob",
            name="match_ids",
            field=models.BooleanField(
                default=False, help_text="Match existing rows by the file's id column."
            ),
        ),
        migrations.AddField(
            model_name="importjob",
            name="keep_ids",
            field=models.BooleanField(
                default=False, help_text="Create rows with the ids the file gives."
            ),
        ),
    ]
