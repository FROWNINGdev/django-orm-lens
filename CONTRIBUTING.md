# Contributing to Django ORM Lens

Thanks for wanting to help! Here is the shortest path from clone to PR.

## Local dev

```bash
git clone https://github.com/FROWNINGdev/django-orm-lens.git
cd django-orm-lens
npm install
npm run build
```

Open the folder in VS Code and press **F5**. A new "Extension Development Host" window launches with the extension loaded. Open the included `examples/` folder in that window to test.

## Project layout

```
src/
  types.ts           # shared interfaces
  parser.ts          # models.py -> WorkspaceIndex
  treeProvider.ts    # VS Code TreeDataProvider
  graphWebview.ts    # Mermaid ER diagram panel
  extension.ts       # activation + command wiring
media/               # icons and screenshots
examples/            # sample Django app for manual testing
```

## Coding rules

- TypeScript strict mode. No `any` unless justified in a comment.
- No runtime dependencies beyond the VS Code API — the extension must stay small and offline-friendly.
- Every user-visible string goes through `vscode.l10n.t()` once i18n is wired (issue #TBD).

## Reporting bugs

Please use the GitHub issue templates. Include:
- VS Code version, OS
- Sample `models.py` (minimized) that reproduces the problem
- Screenshot of the sidebar / diagram if visual

## Pull requests

- One feature per PR, small is better than big.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Match existing code style (Prettier defaults).
