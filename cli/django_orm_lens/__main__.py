"""Entry point for ``python -m django_orm_lens``.

The console scripts declared in pyproject.toml cover the common case, but
``python -m`` is the invocation that does not depend on the scripts directory
being on PATH — which is exactly the situation inside CI images, tox
environments and freshly created venvs. Mirrors what pip, pytest and venv do.

Delegates to the same ``cli.main`` the console script uses, so the two paths
cannot drift.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
