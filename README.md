<div align="center">

<img src="media/hero.png" alt="Django ORM Lens — live sidebar and ER diagram for your Django models in VS Code" width="100%"/>

<br/>
<br/>

# Django ORM Lens

### 🔍 See your entire Django schema. Without leaving the editor.

Every app. Every model. Every field. Every relationship. Grouped, navigable, and one keystroke away from a live ER diagram.

<br/>

[![Install from Marketplace](https://img.shields.io/badge/Install-Marketplace-0c4b33?style=for-the-badge&logo=visualstudiocode&logoColor=white)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![Star on GitHub](https://img.shields.io/badge/★-Star_on_GitHub-24292f?style=for-the-badge&logo=github&logoColor=white)](https://github.com/FROWNINGdev/django-orm-lens)
[![Sponsor](https://img.shields.io/badge/♥-Sponsor-db61a2?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/FROWNINGdev)

<br/>

[![Version](https://img.shields.io/visual-studio-marketplace/v/frowningdev.django-orm-lens?color=0c4b33&label=version&logo=visualstudiocode)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![Installs](https://img.shields.io/visual-studio-marketplace/i/frowningdev.django-orm-lens?color=0c4b33&label=installs)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![Rating](https://img.shields.io/visual-studio-marketplace/r/frowningdev.django-orm-lens?color=0c4b33&label=rating)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens&ssr=false#review-details)
[![License MIT](https://img.shields.io/badge/license-MIT-0c4b33?style=flat)](LICENSE)
[![CI](https://github.com/FROWNINGdev/django-orm-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/FROWNINGdev/django-orm-lens/actions/workflows/ci.yml)

</div>

---

## ⚡ Install in one line

```bash
code --install-extension frowningdev.django-orm-lens
```

Or search **`Django ORM Lens`** in the VS Code Extensions view.

<br/>

## 🎯 The problem

You open a Django project. It has 20 apps. You need to answer a simple question:

> _"Which app owns the `Order` model, and how is it connected to `User`?"_

Today, you do this:

1. `Ctrl+P`, type "models" — scroll through 30 hits
2. Open five files
3. `Ctrl+F` for `class Order`
4. Read through 400 lines of `ForeignKey('otherapp.Something')` strings
5. Try to remember what you learned in step 2

**Half a day gone. Every time. On every project.**

<br/>

## ✨ With Django ORM Lens

<table>
<tr>
<td width="50%" valign="top">

### 📚 A tree of everything

Every app → every model → every field → every `Meta` option. Grouped by application, sorted alphabetically, expandable.

Icons distinguish `CharField` from `ForeignKey` from `ManyToManyField` at a glance.

</td>
<td width="50%" valign="top">

### 🕸️ A live ER diagram

One command opens a Mermaid entity-relationship diagram of your entire schema. Watch it redraw as you edit.

`ForeignKey`, `OneToOneField`, and `ManyToManyField` become proper cardinality arrows.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🧭 Jump-to-definition

Click any field in the tree → cursor lands on the exact line. No file dialog, no fuzzy search.

</td>
<td width="50%" valign="top">

### ⚡ Zero configuration

No `DJANGO_SETTINGS_MODULE`. No `runserver`. Parses `models.py` statically. Works with a broken venv, a missing dependency, or on someone else's laptop.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🔄 Auto-refresh

File watcher rescans on save. Add a field → the tree updates instantly. Change a `ForeignKey` target → the diagram redraws.

</td>
<td width="50%" valign="top">

### 🎨 Native VS Code UI

Dark theme. Light theme. Your theme. Follows your icon theme, your font, your key bindings. Nothing garish, nothing branded, nothing that looks like it came from a marketing deck.

</td>
</tr>
</table>

<br/>

## 📸 What it looks like

<div align="center">
<img src="media/hero.png" alt="Django ORM Lens sidebar showing the blog_app models with fields, relations, and Meta options" width="90%"/>
</div>

<br/>

## 🚀 Get started (30 seconds)

1. Install:
   ```bash
   code --install-extension frowningdev.django-orm-lens
   ```
2. Open any folder that contains a `manage.py` or `models.py`
3. Click the **🔍 Django ORM Lens** icon in the activity bar (left edge)
4. Expand apps → models → fields
5. Click the **type-hierarchy** icon at the top of the panel → ER diagram opens beside your code

That is the entire onboarding. No settings screen. No sign-in. No telemetry.

<br/>

## 🤔 How is this different?

| | **Django ORM Lens** | `django-extensions graph_models` | Django Admin | Manual `Ctrl+F` |
|---|:-:|:-:|:-:|:-:|
| Works without a bootable Django project | ✅ | ❌ | ❌ | ✅ |
| Zero-install | ✅ | ❌ (needs graphviz) | ❌ | ✅ |
| Live-updates on save | ✅ | ❌ | ❌ | ✅ |
| Groups by app | ✅ | ⚠️ | ✅ | ❌ |
| ER diagram | ✅ | ✅ | ❌ | ❌ |
| Jump-to-definition | ✅ | ❌ | ❌ | ⚠️ |
| Runs in VS Code | ✅ | ❌ | ❌ | ✅ |
| Free & open-source | ✅ | ✅ | ✅ | ✅ |

<br/>

## ⚙️ Configuration

The defaults are opinionated and sensible. If you need to tweak:

```jsonc
// .vscode/settings.json
{
  "djangoOrmLens.excludeGlobs": [
    "**/migrations/**",
    "**/node_modules/**",
    "**/venv/**",
    "**/.venv/**",
    "**/env/**"
  ],
  "djangoOrmLens.autoRefresh": true
}
```

| Setting | Type | Default | What it does |
|---|---|---|---|
| `djangoOrmLens.excludeGlobs` | `string[]` | See above | Glob patterns to skip when scanning |
| `djangoOrmLens.autoRefresh` | `boolean` | `true` | Rescan on `models.py` changes |

<br/>

## 🧭 Commands

Open the command palette (`Ctrl+Shift+P` / `Cmd+Shift+P`) and type "Django ORM Lens":

| Command | What it does |
|---|---|
| `Django ORM Lens: Refresh` | Force-rescan the workspace |
| `Django ORM Lens: Show ER Diagram` | Open the Mermaid ER diagram side-by-side |
| `Django ORM Lens: Jump to Model` | Programmatic — triggered by tree clicks |

<br/>

## 🗺️ Roadmap

Public and prioritized. Vote by 👍-ing the [corresponding issue](https://github.com/FROWNINGdev/django-orm-lens/issues).

- [ ] Hover cards over `ForeignKey('app.Model')` in the editor
- [ ] Migration dependency graph
- [ ] Export ER diagram as SVG / PNG
- [ ] Support `models/` package (split-file apps)
- [ ] Support third-party fields (`django-mptt`, `django-model-utils`, `django-taggit`)
- [ ] Filter tree by app / model name
- [ ] **Pro:** cloud-sync schema snapshots for teams, diff between branches, custom ER themes

<br/>

## ❓ FAQ

<details>
<summary><b>Do you send any of my code to a server?</b></summary>
<br/>
No. Every byte stays on your machine. The parser is pure TypeScript, no LLM calls, no telemetry, no analytics, no error reporting. The Mermaid renderer runs inside VS Code's webview sandbox.
</details>

<details>
<summary><b>Does it work with a Poetry / uv / conda project?</b></summary>
<br/>
Yes. The parser reads Python source directly and does not care what package manager you use. It does not even need Python installed.
</details>

<details>
<summary><b>What if my models are split across multiple files inside a <code>models/</code> package?</b></summary>
<br/>
Currently v0.1.0 only scans <code>models.py</code>. Split packages land in v0.2.0 — track <a href="https://github.com/FROWNINGdev/django-orm-lens/issues">the roadmap issue</a>.
</details>

<details>
<summary><b>Can I use it with DRF serializers / Wagtail / Oscar?</b></summary>
<br/>
The tree shows any class that inherits from something ending in <code>Model</code>. DRF <code>ModelSerializer</code>-based classes will appear. Wagtail <code>Page</code> and <code>Snippet</code> subclasses will appear. If you find a case that does not, please open an issue.
</details>

<details>
<summary><b>Is there a version for JetBrains / PyCharm?</b></summary>
<br/>
Not yet. PyCharm already has excellent Django support out of the box, so the value proposition is smaller. If enough people ask, a port becomes worth it.
</details>

<details>
<summary><b>How do I contribute?</b></summary>
<br/>
See <a href="CONTRIBUTING.md">CONTRIBUTING.md</a>. Clone, <code>npm install</code>, <code>npm run build</code>, press F5. Most useful contributions right now: parser edge cases (models/ packages, 2-space indent, custom field types).
</details>

<br/>

## 💚 Support the project

If Django ORM Lens saved you time, here is how you can pay it forward:

<div align="center">

[![Star on GitHub](https://img.shields.io/badge/⭐_Star_the_repo-24292f?style=for-the-badge)](https://github.com/FROWNINGdev/django-orm-lens)
&nbsp;
[![Rate on Marketplace](https://img.shields.io/badge/📝_Rate_on_Marketplace-0c4b33?style=for-the-badge)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens&ssr=false#review-details)
&nbsp;
[![Sponsor](https://img.shields.io/badge/♥_Sponsor-db61a2?style=for-the-badge)](https://github.com/sponsors/FROWNINGdev)

</div>

Every star, every rating, every dollar helps me spend more time building the next feature and less time thinking about whether it is worth it.

<br/>

## 📜 License

MIT © [FROWNINGdev](https://github.com/FROWNINGdev)

<br/>

<div align="center">

**Made for developers who care about their codebase.**

[Marketplace](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens) · [GitHub](https://github.com/FROWNINGdev/django-orm-lens) · [Issues](https://github.com/FROWNINGdev/django-orm-lens/issues) · [Roadmap](https://github.com/FROWNINGdev/django-orm-lens#%EF%B8%8F-roadmap) · [Sponsor](https://github.com/sponsors/FROWNINGdev)

</div>
