"""A session-mode project with django-allauth and sign-in with an ID token, run in a subprocess.

``test_social_token_allauth`` boots it in its own interpreter: allauth's apps
must be installed when Django starts, which the main suite's settings never do.
"""
