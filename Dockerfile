# Pin to a stable Python release. 3.14 is a beta series and its `slim` tag
# can be rebuilt with breaking or security-sensitive changes at any time;
# 3.13 is the current stable, and dependabot.yml holds major bumps for
# manual opt-in so we upgrade only after verifying the extension + MCP
# tools against the new interpreter.
FROM python:3.14-slim

LABEL org.opencontainers.image.title="django-orm-lens"
LABEL org.opencontainers.image.description="Static analysis for Django models. Sidebar tree, ER diagrams, and JSON output for terminals and AI coding agents."
LABEL org.opencontainers.image.source="https://github.com/FROWNINGdev/django-orm-lens"
LABEL org.opencontainers.image.licenses="MIT"

ARG PKG_VERSION
RUN pip install --no-cache-dir "django-orm-lens[mcp]${PKG_VERSION:+==${PKG_VERSION}}"

# Run as a non-root user. The tool only reads static project files, so root
# is not needed at any point. Any path-traversal or unsafe file-read bug in
# the MCP server therefore executes with reduced privilege (uid=10001, no
# home dir, no shell, no ability to write anywhere outside /workspace when
# it's bind-mounted read-write).
RUN adduser --system --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER appuser

WORKDIR /workspace
ENTRYPOINT ["django-orm-lens"]
CMD ["--help"]
