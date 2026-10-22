"""``ChangeLog.action`` gains ``transition``: a StateField moving along a declared transition."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("karni_audit", "0003_request_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="changelog",
            name="action",
            field=models.CharField(
                choices=[
                    ("create", "Created"),
                    ("update", "Updated"),
                    ("delete", "Deleted"),
                    ("restore", "Restored"),
                    ("transition", "Transitioned"),
                ],
                max_length=10,
            ),
        ),
    ]
