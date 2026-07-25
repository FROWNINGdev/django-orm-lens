<!-- Thanks for the PR! A couple of quick checks help me review faster. -->

## Summary

<!-- One or two sentences: what changed and why. Skip the redundant "this PR does X" preamble. -->

## Type of change

<!-- Tick everything that applies. -->

- [ ] Bug fix (non-breaking, restores expected behaviour)
- [ ] Feature (non-breaking, adds a capability)
- [ ] Breaking change (existing users have to update config or code)
- [ ] Docs / README / comments only (no runtime effect)
- [ ] Internal refactor (no behaviour change, no public API change)
- [ ] Dependency bump
- [ ] CI / build / tooling

## Test plan

<!--
How did you verify this locally? A concrete recipe beats "I tested it".
Example:
  cd cli && pytest tests/test_mcp_workspace.py -v
  npm test
  docker build -t local . && docker run --rm local --version
Or list the new tests you added.
-->

## Checklist

- [ ] I ran the full test suite locally (`cd cli && pytest -q` for Python, `npm test` for TypeScript) and it is green
- [ ] I added or updated tests that cover the change (bugfixes should get a regression test)
- [ ] If the change is user-facing I updated the CHANGELOG under `## [Unreleased]`
- [ ] If the change touches the MCP tool contract (new tool, new arg, new error code) I updated the tool description in `mcp_server.py` and the relevant tests in `test_mcp_server.py`
- [ ] If this is a breaking change I called it out under `## Summary` above and suggested a migration path

## Related issues / discussions

<!--
Closes #123
Refs #456
Discussion: https://github.com/FROWNINGdev/django-orm-lens/discussions/28
-->
