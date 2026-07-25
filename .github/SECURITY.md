# Security Policy

Thank you for taking the time to report a vulnerability responsibly.

## Supported Versions

Security fixes land on the latest minor release of each distribution.
Older minors receive fixes only when the vulnerability is critical
(CVSS 9.0+) or actively exploited.

| Distribution              | Supported                    |
|---------------------------|------------------------------|
| VS Code extension         | Latest `0.x` release         |
| Python package (`pip`)    | Latest `1.x` release         |
| Docker image (GHCR)       | `latest` and current minor   |
| MCP Registry entry        | Latest published version     |

Legacy versions in the tables above receive best-effort fixes only. If
you rely on an older release for a real reason, please open a
Discussion and I will consider a backport case-by-case.

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**
Public issues let attackers weaponise the report before the patch ships.

Please use one of these private channels instead:

1. **Preferred — GitHub Private Security Advisory.** Open
   [github.com/FROWNINGdev/django-orm-lens/security/advisories/new](https://github.com/FROWNINGdev/django-orm-lens/security/advisories/new).
   This gives us an encrypted thread, keeps the reporter credited, and
   lets us request a CVE once the fix is ready.
2. **Alternative — email.** Send to `frowningdev@gmail.com` with
   subject `[django-orm-lens SECURITY]`. Include a clear reproducer,
   the affected version, and a proof-of-concept if you have one.

## What to expect

* **Acknowledgement** — within **48 hours** of receipt.
* **Triage + severity assessment** — within **5 business days**.
* **Fix + coordinated disclosure** — target **14 days** for
  high-severity, **30 days** for low-severity issues. Complex fixes may
  need longer; we will keep you updated in the same thread.
* **Credit** — reporters are named in the CHANGELOG and the security
  advisory unless they ask to stay anonymous.

## Scope

In-scope: the code shipped as
`frowningdev.django-orm-lens` (VS Code Marketplace + Open VSX),
`django-orm-lens` (PyPI), and `ghcr.io/frowningdev/django-orm-lens`
(GHCR image). This includes the MCP server, the static analysis
parser, and the CLI.

Out of scope: vulnerabilities in the Django framework itself
(report to <https://www.djangoproject.com/security/>), in the `mcp`
runtime package (report to
<https://github.com/modelcontextprotocol/python-sdk>), in third-party
MCP clients (Cursor, Aider, Claude Desktop), or in the Node.js runtime
used by the VS Code extension.

## Safe-harbour statement

We will not pursue legal action against researchers who follow this
policy in good faith, avoid data exfiltration or service disruption,
and give us reasonable time to fix before public disclosure.
