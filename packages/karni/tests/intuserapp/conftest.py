"""The integer-keyed user's flows run only when that user is installed.

``tests/accounts/test_integer_user.py`` runs this directory in a subprocess
with ``KARNI_TEST_USER_PK=bigint``. In the main run it is not collected.
"""

from __future__ import annotations

import os

collect_ignore_glob = [] if os.environ.get("KARNI_TEST_USER_PK") == "bigint" else ["test_*.py"]
