# syntax=docker/dockerfile:1
# The `karni` command (karni-cli + karni) from PyPI, for machines without
# Python 3.12. Published as ghcr.io/cbsshekhawat18-lab/karni by
# .github/workflows/container.yml.
#
#   docker run --rm -it -u "$(id -u):$(id -g)" -v "$PWD:/work" \
#     ghcr.io/cbsshekhawat18-lab/karni new "Ticket Shop"
#
# It runs the CLI; a generated project runs from its own docker-compose.yml.
FROM python:3.12-slim

ARG KARNI_VERSION
RUN test -n "$KARNI_VERSION" \
 && pip install --no-cache-dir --disable-pip-version-check \
      "karni==${KARNI_VERSION}" "karni-cli==${KARNI_VERSION}"

LABEL org.opencontainers.image.title="karni" \
      org.opencontainers.image.description="The karni command: scaffold and grow Django + React projects with Karni." \
      org.opencontainers.image.source="https://github.com/cbsshekhawat18-lab/karni" \
      org.opencontainers.image.documentation="https://cbsshekhawat18-lab.github.io/karni/" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${KARNI_VERSION}"

# Any uid can run it (`-u "$(id -u):$(id -g)"` keeps generated files yours):
# HOME is writable for every user.
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["karni"]
CMD ["--help"]
