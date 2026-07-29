# Pin to a stable Python release. 3.14 is a beta series and its `slim` tag
# can be rebuilt with breaking or security-sensitive changes at any time;
# 3.13 is the current stable, and dependabot.yml holds major bumps for
# manual opt-in so we upgrade only after verifying the extension + MCP
# tools against the new interpreter.
FROM python:3.13-slim

LABEL org.opencontainers.image.title="django-orm-lens"
LABEL org.opencontainers.image.description="Static analysis for Django models. Sidebar tree, ER diagrams, and JSON output for terminals and AI coding agents."
LABEL org.opencontainers.image.source="https://github.com/FROWNINGdev/django-orm-lens"
LABEL org.opencontainers.image.licenses="MIT"

ARG PKG_VERSION

# Retry the install rather than trusting a pre-flight check.
#
# Right after a release, PyPI's simple index is served from Fastly and its
# edges do not all update together. On py-v1.6.0 the workflow's wait step
# polled the index and correctly saw 1.6.0 — and pip inside this build, on a
# different edge, still resolved 1.5.1 as newest and failed with "No matching
# distribution found". A check from one network path cannot promise what
# another path will see, so waiting longer would not have helped.
#
# `pip show` afterwards is the real gate: if every attempt failed we must not
# produce an image that silently lacks the package.
RUN set -eu; \
    for attempt in 1 2 3 4 5 6; do \
      if pip install --no-cache-dir "django-orm-lens[mcp]${PKG_VERSION:+==${PKG_VERSION}}"; then \
        break; \
      fi; \
      echo "pip attempt ${attempt} failed - PyPI edge may still be stale, retrying in 30s"; \
      sleep 30; \
    done; \
    pip show django-orm-lens > /dev/null

# Run as a non-root user. The tool only reads static project files, so root
# is not needed at any point. Any path-traversal or unsafe file-read bug in
# the MCP server therefore executes with reduced privilege (uid=10001, no
# home dir, no shell, no ability to write anywhere outside /workspace when
# it's bind-mounted read-write).
RUN adduser --system --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER appuser

WORKDIR /workspace

# Default to the MCP server, not the help text.
#
# Directories that index MCP servers - Glama among them - build the repo's
# Dockerfile and then try to speak MCP to the container over stdio. With
# `--help` as the default the process printed usage and exited, so the
# handshake never happened and the build counted as broken.
#
# Only CMD changes, so every documented CLI invocation is untouched: passing
# arguments overrides CMD, and `docker run ... scan --path .` behaves exactly
# as before.
ENTRYPOINT ["django-orm-lens"]
CMD ["mcp"]
