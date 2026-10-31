# django-orm-lens is now orm-lens

This project was renamed to **[orm-lens](https://pypi.org/project/orm-lens/)** when it started covering SQLAlchemy and Alembic as well as Django.

Installing `django-orm-lens` installs the matching `orm-lens` release, so nothing breaks:

- the `django-orm-lens` and `django-orm-lens-mcp` commands keep working, next to the new `orm-lens` and `orm-lens-mcp`;
- `pip install "django-orm-lens[mcp]"` still pulls in the MCP server;
- `import django_orm_lens` still resolves.

New installs should use the new name:

```bash
pip install orm-lens
uvx orm-lens scan
```

Source, docs and issues: https://github.com/FROWNINGdev/orm-lens
