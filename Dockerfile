FROM python:3.14-slim

LABEL org.opencontainers.image.title="django-orm-lens"
LABEL org.opencontainers.image.description="Static analysis for Django models. Sidebar tree, ER diagrams, and JSON output for terminals and AI coding agents."
LABEL org.opencontainers.image.source="https://github.com/FROWNINGdev/django-orm-lens"
LABEL org.opencontainers.image.licenses="MIT"

ARG PKG_VERSION
RUN pip install --no-cache-dir "django-orm-lens[mcp]${PKG_VERSION:+==${PKG_VERSION}}"

WORKDIR /workspace
ENTRYPOINT ["django-orm-lens"]
CMD ["--help"]
