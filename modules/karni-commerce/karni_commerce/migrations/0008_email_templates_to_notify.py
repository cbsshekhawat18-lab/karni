"""Commerce's edited emails move to the notifications contract (karni.notify).

Every email a business rewrote (karni_commerce.EmailTemplate) is copied to
notify.EmailTemplate with its dates and authors, then commerce's table goes
(:mod:`karni.notify.adopt`). A project without karni.notify that edited no
email loses nothing. One that edited some is stopped (E446) before anything
is dropped.
"""

from typing import Any

from django.db import migrations
from karni.notify.adopt import adopt_edited_emails, installed, return_edited_emails

SOURCE = "karni_commerce.EmailTemplate"


def forwards(apps: Any, schema_editor: Any) -> None:
    adopt_edited_emails(apps, schema_editor, SOURCE)


def backwards(apps: Any, schema_editor: Any) -> None:
    return_edited_emails(apps, schema_editor, SOURCE)


class Migration(migrations.Migration):
    dependencies = [
        ("karni_commerce", "0007_order_deposit"),
        # the contract's table must exist before the rows are copied to it
        *([("notify", "0001_initial")] if installed() else []),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.DeleteModel(name="EmailTemplate"),
    ]
