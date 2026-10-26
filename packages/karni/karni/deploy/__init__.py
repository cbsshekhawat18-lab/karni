"""What a Karni project needs to run in production, as small runnable modules.

* :mod:`karni.deploy.entrypoint`: the production image's entrypoint. It runs
  ``karni check --deploy`` and starts the container's command only when the
  checks pass (``KARNI_SKIP_DEPLOY_CHECK=1`` is the logged emergency exit).
* :mod:`karni.deploy.healthcheck`: the probe a container health check runs. It
  asks ``/health/`` with the host and scheme the production settings accept.
* :mod:`karni.deploy.backup`: database and media backups with retention, to a
  directory or an S3 bucket, and the restore. Standard library only, so the
  backup container runs it next to ``pg_dump`` without Django.

``manage.py karni_publish_web`` writes the web server's files (the Caddyfile,
the built staff app and the security headers) into the shared volume.

The generated ``docker-compose.prod.yml`` (``karni make deploy compose``) wires
them together. Nothing here imports Django at module level, so each module
starts fast as ``python -m karni.deploy.<name>``. docs/deploy.md is the guide.
"""
