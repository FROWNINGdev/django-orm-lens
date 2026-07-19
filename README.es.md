[English](README.md) · [Русский](README.ru.md) · **Español** · [中文](README.zh.md)

<div align="center">

<img src="media/hero.png" alt="Django ORM Lens — barra lateral en vivo y diagrama ER para tus modelos de Django" width="100%"/>

<br/>
<br/>

# Django ORM Lens

### Visualiza todo tu esquema de Django — en tu editor, en tu terminal y desde tu agente de IA.

Cada aplicación. Cada modelo. Cada campo. Cada relación. Agrupados, navegables y a un atajo de teclado de un diagrama ER en vivo.

<br/>

[![Install from Marketplace](https://img.shields.io/badge/VS_Code-Install-0c4b33?style=for-the-badge&logo=visualstudiocode&logoColor=white)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![PyPI](https://img.shields.io/badge/PyPI-pip_install-3775a9?style=for-the-badge&logo=pypi&logoColor=white)](https://pypi.org/project/django-orm-lens/)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-listed-6f42c1?style=for-the-badge)](https://registry.modelcontextprotocol.io/)
[![Glama](https://img.shields.io/badge/Glama-listed-0f172a?style=for-the-badge)](https://glama.ai/mcp/servers/FROWNINGdev/django-orm-lens)
[![mcp.so](https://img.shields.io/badge/mcp.so-listed-1f2937?style=for-the-badge)](https://mcp.so/servers/django-orm-lens)
[![Star on GitHub](https://img.shields.io/badge/★-Star_on_GitHub-24292f?style=for-the-badge&logo=github&logoColor=white)](https://github.com/FROWNINGdev/django-orm-lens)
[![Sponsor](https://img.shields.io/badge/♥-Sponsor-db61a2?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/FROWNINGdev)

<br/>

[![Version](https://img.shields.io/visual-studio-marketplace/v/frowningdev.django-orm-lens?color=0c4b33&label=extension&logo=visualstudiocode)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![Installs](https://img.shields.io/visual-studio-marketplace/i/frowningdev.django-orm-lens?color=0c4b33&label=installs)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![Rating](https://img.shields.io/visual-studio-marketplace/r/frowningdev.django-orm-lens?color=0c4b33&label=rating)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens&ssr=false#review-details)
[![PyPI version](https://img.shields.io/pypi/v/django-orm-lens?color=3775a9&label=pypi)](https://pypi.org/project/django-orm-lens/)
[![Python](https://img.shields.io/pypi/pyversions/django-orm-lens?color=3775a9)](https://pypi.org/project/django-orm-lens/)
[![License MIT](https://img.shields.io/badge/license-MIT-0c4b33?style=flat)](LICENSE)
[![CI](https://github.com/FROWNINGdev/django-orm-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/FROWNINGdev/django-orm-lens/actions/workflows/ci.yml)

</div>

---

## 🎯 Elige tu camino

Django ORM Lens se distribuye como **tres distribuciones sobre un mismo núcleo** — elige la que se ajuste a tu flujo de trabajo. Cada una toma menos de 60 segundos.

**Usuario de editor (VS Code / Cursor / Windsurf):** instala la extensión → abre cualquier proyecto Django → aparecen el árbol lateral y el diagrama ER.

```bash
code --install-extension frowningdev.django-orm-lens
```

**Usuario de terminal / CI:** instala desde PyPI → ejecuta `django-orm-lens` en cualquier directorio que contenga aplicaciones Django.

```bash
pip install django-orm-lens
django-orm-lens               # welcome + commands
django-orm-lens scan          # scan cwd for apps and models
```

**Usuario de agente de codificación con IA (Cursor / Aider / Continue / Zed):** instala con los extras MCP → agrega un bloque JSON a la configuración de tu cliente.

```bash
pip install "django-orm-lens[mcp]"
```

Luego usa el fragmento de configuración MCP de la sección [Integraciones](#-integrations) más abajo. Apunta `DJANGO_ORM_LENS_ROOT` a la ruta absoluta de tu proyecto Django.

---

## 📊 Tracción

<div align="center">

<!-- Headline split-badges (dark label · colored value) -->

[![First-week installs](https://img.shields.io/badge/first--week_installs-1814-3775a9?style=for-the-badge&logo=pypi&logoColor=white&labelColor=1e293b)](https://pypi.org/project/django-orm-lens/)
[![Peak day](https://img.shields.io/badge/peak_day_installs-441-f97316?style=for-the-badge&logo=rocket&logoColor=white&labelColor=1e293b)](https://pypi.org/project/django-orm-lens/)
[![Unique cloners](https://img.shields.io/badge/unique_cloners_14d-279-24292f?style=for-the-badge&logo=github&logoColor=white&labelColor=1e293b)](https://github.com/FROWNINGdev/django-orm-lens)
[![VS Code rating](https://img.shields.io/badge/VS_Code_rating-5.0_%E2%98%85-eab308?style=for-the-badge&logo=visualstudiocode&logoColor=white&labelColor=1e293b)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)

<br/>

<!-- Cross-platform reach snapshot -->

[![VS Code installs](https://img.shields.io/badge/VS_Code_installs-6-0c4b33?style=for-the-badge&logo=visualstudiocode&logoColor=white&labelColor=1e293b)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![GitHub views](https://img.shields.io/badge/GitHub_views_14d-381-24292f?style=for-the-badge&logo=github&logoColor=white&labelColor=1e293b)](https://github.com/FROWNINGdev/django-orm-lens)
[![LinkedIn posts](https://img.shields.io/badge/LinkedIn_posts_live-7-0a66c2?style=for-the-badge&logo=linkedin&logoColor=white&labelColor=1e293b)](https://linkedin.com/company/django-orm-lens)
[![Awesome-list PRs](https://img.shields.io/badge/awesome--list_PRs-4_pending-16a34a?style=for-the-badge&logo=awesomelists&logoColor=white&labelColor=1e293b)](https://github.com/FROWNINGdev)
[![Community PRs merged](https://img.shields.io/badge/community_PRs_merged-5-8b5cf6?style=for-the-badge&logo=github&logoColor=white&labelColor=1e293b)](https://github.com/FROWNINGdev/django-orm-lens/pulls?q=is%3Apr+is%3Amerged+-author%3AFROWNINGdev)

<br/>

<!-- Live counters + directories -->

[![PyPI downloads total](https://img.shields.io/pepy/dt/django-orm-lens?style=for-the-badge&logo=pypi&logoColor=white&label=total%20downloads&labelColor=1e293b&color=3775a9)](https://pepy.tech/project/django-orm-lens)
[![PyPI weekly](https://img.shields.io/badge/weekly_downloads-1895-3775a9?style=for-the-badge&logo=pypi&logoColor=white&labelColor=1e293b)](https://pepy.tech/project/django-orm-lens)
[![GitHub stars](https://img.shields.io/github/stars/FROWNINGdev/django-orm-lens?style=for-the-badge&logo=github&logoColor=white&label=stars&labelColor=1e293b&color=eab308)](https://github.com/FROWNINGdev/django-orm-lens/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/FROWNINGdev/django-orm-lens?style=for-the-badge&logo=github&logoColor=white&label=forks&labelColor=1e293b&color=64748b)](https://github.com/FROWNINGdev/django-orm-lens/network/members)

<br/>

<!-- MCP directories -->

[![MCP Registry](https://img.shields.io/badge/MCP_Registry-official_listing-6f42c1?style=for-the-badge&labelColor=1e293b)](https://registry.modelcontextprotocol.io/)
[![CodeTriage](https://img.shields.io/badge/CodeTriage-help_triage-2ec4b6?style=for-the-badge&labelColor=1e293b)](https://www.codetriage.com/frowningdev/django-orm-lens)
[![Glama.ai](https://img.shields.io/badge/Glama.ai-listed-0f172a?style=for-the-badge&labelColor=1e293b)](https://glama.ai/mcp/servers/FROWNINGdev/django-orm-lens)
[![mcp.so](https://img.shields.io/badge/mcp.so-listed-1f2937?style=for-the-badge&labelColor=1e293b)](https://mcp.so/servers/django-orm-lens)

<br/>

<!-- Tech stack + license -->

[![VS Code v0.5.1](https://img.shields.io/badge/VS_Code-v0.5.1-0c4b33?style=for-the-badge&logo=visualstudiocode&logoColor=white&labelColor=1e293b)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![PyPI version](https://img.shields.io/pypi/v/django-orm-lens?style=for-the-badge&logo=pypi&logoColor=white&label=PyPI&labelColor=1e293b&color=3775a9)](https://pypi.org/project/django-orm-lens/)
[![Python](https://img.shields.io/pypi/pyversions/django-orm-lens?style=for-the-badge&logo=python&logoColor=white&label=Python&labelColor=1e293b&color=3775a9)](https://pypi.org/project/django-orm-lens/)
[![Django](https://img.shields.io/badge/Django-4.0_%E2%80%93_5.1-092e20?style=for-the-badge&logo=django&logoColor=white&labelColor=1e293b)](https://www.djangoproject.com/)
[![License MIT](https://img.shields.io/badge/license-MIT-16a34a?style=for-the-badge&labelColor=1e293b)](LICENSE)

</div>

<sub><i>Actualizado el 2026-07-19. Las estrellas / forks de GitHub y el total de descargas (vía pepy.tech) se actualizan automáticamente en vivo; el conteo semanal y las versiones de VS Code / PyPI se actualizan con cada lanzamiento.</i></sub>

> Si la herramienta te ahorra un `grep` la próxima vez que toques un proyecto Django ajeno — **[una estrella ayuda a que otros lo encuentren](https://github.com/FROWNINGdev/django-orm-lens/stargazers)**.

---

## ⚡ Instalación

**VS Code / Cursor / Windsurf / cualquier fork de Code:**

```bash
code --install-extension frowningdev.django-orm-lens
```

O busca **`Django ORM Lens`** en la vista de Extensiones.

**Terminal y agentes de codificación con IA:**

```bash
pip install django-orm-lens              # CLI only
pip install "django-orm-lens[mcp]"       # + MCP server for AI agents
```

Requiere Python 3.9+. Cero dependencias en tiempo de ejecución para la CLI.

<br/>

## 🎯 El problema

> **Funciona sin conexión. Funciona con un venv roto. Funciona en el portátil de alguien más. Funciona en CI.**

Abres un proyecto Django. Tiene 20 aplicaciones. Necesitas responder a una pregunta sencilla:

> _"¿Qué aplicación es dueña del modelo `Order` y cómo se relaciona con `User`?"_

Hoy, eso significa: `Ctrl+P`, "models", desplázate por 30 resultados, abre cinco archivos, `Ctrl+F` para `class Order`, lee 400 líneas de cadenas `ForeignKey('otherapp.Something')`, y trata de recordar lo que aprendiste dos archivos atrás.

**Medio día perdido. Cada vez. En cada proyecto.**

<br/>

## ✨ Con Django ORM Lens

<table>
<tr>
<td width="50%" valign="top">

### 📚 Un árbol de todo

Cada aplicación → cada modelo → cada campo → cada opción `Meta`. Agrupados por aplicación, ordenados alfabéticamente, expandibles.

Los iconos distinguen `CharField` de `ForeignKey` de `ManyToManyField` de un vistazo.

</td>
<td width="50%" valign="top">

### 🕸️ Un diagrama ER en vivo

Un comando abre un diagrama entidad-relación de Mermaid de todo tu esquema. Míralo redibujarse mientras editas. Exporta a SVG.

`ForeignKey`, `OneToOneField` y `ManyToManyField` se convierten en flechas de cardinalidad adecuadas.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🔎 Hover sobre las relaciones

Pasa el cursor sobre `ForeignKey('app.Model')` en cualquier archivo Python → aparece una tarjeta con los campos, relaciones y un enlace "Ir a" del modelo destino. Sin `Ctrl+F`, sin diálogo de archivos.

</td>
<td width="50%" valign="top">

### 🧭 Ir a la definición

Haz clic en cualquier campo del árbol → el cursor aterriza en la línea exacta. Filtra el árbol por nombre de aplicación o modelo. Los paquetes `models/` divididos son totalmente compatibles.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### ⚡ Cero configuración

Sin `DJANGO_SETTINGS_MODULE`. Sin `runserver`. Analiza `models.py` de forma estática. Funciona con un venv roto, una dependencia faltante o en el portátil de alguien más.

</td>
<td width="50%" valign="top">

### 🎨 Interfaz nativa de VS Code

Tema oscuro. Tema claro. Tu tema. Respeta tu tema de iconos, tu fuente, tus atajos de teclado. Nada estridente, nada con marca.

</td>
</tr>
</table>

<br/>

## 📸 Cómo se ve

<div align="center">
<img src="media/hero.png" alt="Barra lateral de Django ORM Lens mostrando los modelos de una aplicación con campos, relaciones y opciones Meta" width="90%"/>
</div>

**También incluido en la extensión:**

- 🕸️ **Diagrama ER en vivo** — flechas de cardinalidad Mermaid, etiquetas de aristas (`CASCADE`, `through Model`, `as related_name`), consciente del tema, exportación a SVG con un clic
- 🔎 **Tarjetas de hover** — sobre cualquier `ForeignKey('app.Model')` o `ManyToManyField(...)`, con enlace de salto en un clic
- 🧭 **CodeLens** — encima de cada línea `class Model`: recuento de campos, recuento de relaciones y una acción **Open ER diagram**
- 🎨 **Temas nombrados** — `auto` / `default` / `dark` / `forest` / `neutral` para la vista web del diagrama

<br/>

## 🤖 Para terminales y agentes de codificación con IA

El mismo analizador que impulsa la extensión de VS Code se distribuye como un paquete de Python independiente — con un **servidor MCP (Model Context Protocol)** opcional para que cualquier agente de IA compatible con MCP pueda navegar tu esquema de Django sin importar Django ni arrancar tu aplicación.

### CLI

```bash
django-orm-lens scan -f json          # every app, every model, every field
django-orm-lens describe blog.Post    # one model in Markdown
django-orm-lens hover blog.Post       # compact hover card
django-orm-lens list | fzf            # flat app.Model — pipes anywhere
django-orm-lens er > schema.mmd       # Mermaid ER diagram
```

Cada comando acepta `--path <dir>` y `--exclude <glob>`.

### Servidor MCP

Regístralo una vez con tu agente y expondrá cinco herramientas de solo lectura:

| Herramienta | Propósito |
| --- | --- |
| `list_apps` | Cada aplicación Django en el espacio de trabajo con recuento de modelos |
| `list_models` | Lista plana `app.Model`, filtro opcional por aplicación |
| `describe_model` | Detalle completo de campos / relaciones / Meta de un modelo |
| `find_relations` | Relaciones entrantes + salientes de un modelo |
| `er_diagram` | `erDiagram` de Mermaid para todo el espacio de trabajo |

```bash
# Start it directly
django-orm-lens-mcp

# Or via the CLI subcommand
django-orm-lens mcp
```

Establece `DJANGO_ORM_LENS_ROOT=/abs/path/to/project` para apuntarlo a cualquier ubicación.

<br/>

## 🔌 Integraciones

| Cliente | Cómo activarlo | Estado |
|---|---|:-:|
| **VS Code** | `code --install-extension frowningdev.django-orm-lens` | ✅ |
| **Cursor** | mismo VSIX + entrada MCP opcional en `~/.cursor/mcp.json` | ✅ |
| **Windsurf / VSCodium / cualquier fork de Code** | instala el VSIX desde el [Marketplace](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens) o desde [GitHub Releases](https://github.com/FROWNINGdev/django-orm-lens/releases) | ✅ |
| **Aider** | agrega `django-orm-lens-mcp` a tu `mcp.json` | ✅ (vía MCP) |
| **Continue.dev** | registra el servidor MCP en `~/.continue/config.json` | ✅ (vía MCP) |
| **Zed** | registra el servidor MCP en la configuración de Zed | ✅ (vía MCP) |
| **Cualquier cliente compatible con MCP** | apunta `command` a `django-orm-lens-mcp`, establece `DJANGO_ORM_LENS_ROOT` | ✅ |
| **Descubrible en el [Registro MCP](https://registry.modelcontextprotocol.io/)** | directorio oficial de servidores Model Context Protocol | ✅ |
| **Terminal simple / CI** | `pip install django-orm-lens && django-orm-lens scan` | ✅ |

### Ejemplo: Cursor / cualquier cliente MCP

```jsonc
{
  "mcpServers": {
    "django-orm-lens": {
      "command": "django-orm-lens-mcp",
      "env": { "DJANGO_ORM_LENS_ROOT": "/abs/path/to/your/project" }
    }
  }
}
```

<br/>

## 🚀 Primeros pasos (30 segundos)

**En VS Code:**

1. `code --install-extension frowningdev.django-orm-lens`
2. Abre una carpeta con un `manage.py` o `models.py`
3. Haz clic en el icono **Django ORM Lens** en la barra de actividades
4. Expande aplicaciones → modelos → campos
5. Haz clic en el icono **type-hierarchy** en la parte superior del panel → el diagrama ER se abre junto a tu código

**En una terminal:**

```bash
pip install django-orm-lens
cd my-django-project
django-orm-lens scan -f table
```

**Como herramienta de agente de IA:**

```bash
pip install "django-orm-lens[mcp]"
```

…y luego registra `django-orm-lens-mcp` en la configuración MCP de tu agente (consulta la tabla de [Integraciones](#-integrations) arriba).

Sin pantalla de configuración. Sin inicio de sesión. Sin telemetría.

<br/>

## 🎯 Para quién es esto

- **Desarrolladores de Django** que se incorporan a un código base con más de 10 aplicaciones y se pierden en la maraña de `models.py`.
- **Ingenieros por contrato / freelance** que necesitan entender un proyecto Django desconocido en la primera hora, no en la primera semana.
- **Equipos que incorporan nuevos empleados** que quieren una vista del esquema de un vistazo sin levantar infraestructura de documentación.
- **Usuarios avanzados de agentes de IA** (Cursor / Aider / Zed / Continue / cualquier cliente compatible con MCP) que necesitan que el agente responda preguntas sobre el esquema con precisión — sin darle credenciales de base de datos ni arrancar Django.
- **Pipelines de CI** que verifican la forma del esquema (p. ej. "¿accidentalmente rompimos un `related_name`?") sin importar el proyecto.
- **Desarrolladores indie en solitario** con un venv roto o el portátil de alguien más — sin `runserver`, sin `manage.py migrate`, y aún así funciona.

<br/>

## 🗺️ Posición en el mercado

Django ORM Lens se sitúa en la intersección entre las **herramientas de editor** y las **herramientas de agentes de IA** — un espacio que ningún paquete existente cubre:

| Segmento | Opción existente | Lo que te cuesta |
|---|---|---|
| Arrancar y graficar | `django-extensions graph_models` | Requiere Graphviz + settings de Django + una URL de base de datos funcional |
| Visor basado en web | `django-schema-graph` | Requiere un servidor Django en ejecución; una cosa más que puede romperse |
| Panel de administración | Django Admin | Requiere runserver + auth + base de datos — genial para datos, no para arquitectura |
| Plugin de editor | Django Structure de PyCharm | Bloqueado a PyCharm; sin CLI, sin historia para agentes de IA |
| Servidor MCP | (ninguno hasta ahora) | Los agentes de IA adivinan tu esquema a partir del código fuente, de forma imperfecta |

**Django ORM Lens es la única herramienta que entrega tres superficies desde un mismo analizador:** una extensión de VS Code (cualquier fork de Code), una CLI sin dependencias (terminales + CI) y un servidor MCP (agentes de IA). Todo estático. Todo gratis. Todo MIT.

<br/>

## 🤔 ¿En qué se diferencia?

| | **Django ORM Lens** | `django-extensions graph_models` | `django-schema-graph` | Django Admin | PyCharm Django Structure |
|---|:-:|:-:|:-:|:-:|:-:|
| Funciona sin un proyecto Django arrancable | ✅ | ❌ | ❌ | ❌ | ⚠️ |
| Cero instalación (sin graphviz, sin servidor) | ✅ | ❌ | ❌ | ❌ | ❌ (necesita PyCharm) |
| Funciona en VS Code / Cursor / cualquier fork de Code | ✅ | ❌ | ❌ | ❌ | ❌ |
| Árbol lateral dentro del editor | ✅ | ❌ | ❌ | ❌ | ✅ |
| Diagrama ER en vivo | ✅ | ✅ | ✅ | ❌ | ❌ |
| Tarjetas de hover sobre `ForeignKey` | ✅ | ❌ | ❌ | ❌ | ⚠️ |
| CodeLens sobre clases de modelo | ✅ | ❌ | ❌ | ❌ | ❌ |
| Soporte para paquetes `models/` divididos | ✅ | ⚠️ | ⚠️ | ✅ | ✅ |
| CLI para terminal / CI | ✅ | ⚠️ | ❌ | ❌ | ❌ |
| Servidor MCP para agentes de IA | ✅ | ❌ | ❌ | ❌ | ❌ |
| Descubrible en el [Registro MCP](https://registry.modelcontextprotocol.io/) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Gratis y de código abierto (MIT) | ✅ | ✅ | ✅ | ✅ | ❌ (IDE de pago) |
| Soporte de versiones de Django | **4.0 – 5.2** | último | 3.2 – 4.1 (sin actualizaciones desde 2023) | último | último |

> *`django-schema-graph` no se ha actualizado desde 2023-05 y no prueba Django 5.x.*

<br/>

## ⚙️ Configuración

Los valores predeterminados son opinados y razonables. Si necesitas ajustarlos:

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

| Ajuste | Tipo | Predeterminado | Qué hace |
|---|---|---|---|
| `djangoOrmLens.excludeGlobs` | `string[]` | Ver arriba | Patrones glob a omitir durante el escaneo |
| `djangoOrmLens.autoRefresh` | `boolean` | `true` | Reescanea al cambiar `models.py` |

<br/>

## 🧭 Comandos

Abre la paleta de comandos (`Ctrl+Shift+P` / `Cmd+Shift+P`) y escribe "Django ORM Lens":

| Comando | Qué hace |
|---|---|
| `Django ORM Lens: Refresh` | Fuerza un reescaneo del espacio de trabajo |
| `Django ORM Lens: Show ER Diagram` | Abre el diagrama ER de Mermaid en paralelo |
| `Django ORM Lens: Filter Models` | Filtra el árbol por nombre de aplicación / modelo / campo |
| `Django ORM Lens: Clear Filter` | Restaura el árbol completo |
| `Django ORM Lens: Jump to Model` | Programático — activado por clics en el árbol y tarjetas de hover |

<br/>

## 🗺️ Hoja de ruta

**Entregado**

- [x] Árbol lateral agrupado por aplicación
- [x] Diagrama ER de Mermaid en vivo
- [x] Tarjetas de hover sobre `ForeignKey('app.Model')`
- [x] Filtrado del árbol por nombre
- [x] Soporte para paquetes `models/` divididos
- [x] Exportación del diagrama ER como SVG
- [x] CLI de Python + servidor MCP para terminales y agentes de IA
- [x] Vista de bienvenida para espacios de trabajo vacíos
- [x] Ir a la definición seguro de rutas y markdown de hover saneado
- [x] **v0.3.0** — CodeLens encima de cada clase de modelo (`N fields · N relations · Open ER diagram`)
- [x] **v0.3.0** — Etiquetas de arista en el diagrama (`CASCADE`, `SET_NULL`, `PROTECT`, `related_name`)
- [x] **v0.3.0** — Temas de color nombrados (`auto` / `default` / `dark` / `forest` / `neutral`)
- [x] **v0.3.1** — `through_model` en aristas M2M (contribuido por [@kingrubic](https://github.com/kingrubic))
- [x] **v0.3.1** — Listado en el [Registro MCP oficial](https://registry.modelcontextprotocol.io/) + [Glama.ai](https://glama.ai/mcp/servers/FROWNINGdev/django-orm-lens)

**Siguiente**

- [ ] Zoom + minimapa + auto-layout dentro de la vista web ([#4](https://github.com/FROWNINGdev/django-orm-lens/issues/4))
- [ ] Autocompletado de consultas ORM dentro de `.filter()` / `.exclude()` / `.annotate()` ([#3](https://github.com/FROWNINGdev/django-orm-lens/issues/3))
- [ ] Casillas de activación de aplicaciones / modelos para despejar esquemas enormes

**Más adelante**

- [ ] Grafo de dependencias de migraciones
- [ ] Soporte para campos de terceros (`django-mptt`, `django-taggit`, `django-model-utils`)
- [ ] Plugin de JetBrains / PyCharm (si hay demanda)

Vota dando 👍 al [issue](https://github.com/FROWNINGdev/django-orm-lens/issues) correspondiente.

<br/>

## ❓ Preguntas frecuentes

<details>
<summary><b>¿Envían algo de mi código a un servidor?</b></summary>
<br/>
No. Cada byte se queda en tu máquina. El analizador es TypeScript puro (extensión) o Python puro (CLI). Sin llamadas a LLM, sin telemetría, sin analíticas, sin informes de errores. El renderizador de Mermaid corre dentro del sandbox de webview de VS Code.
</details>

<details>
<summary><b>¿Funciona con Poetry / uv / conda / sin venv en absoluto?</b></summary>
<br/>
Sí. La extensión lee el código fuente de Python directamente — no importa Django y no le importa qué gestor de paquetes uses. La CLI requiere Python 3.9+, pero eso es todo.
</details>

<details>
<summary><b>Mis modelos están divididos en varios archivos dentro de un paquete <code>models/</code>. ¿Funciona eso?</b></summary>
<br/>
Sí, desde la v0.2.0. Tanto la extensión como la CLI recorren <code>models/*.py</code> junto al clásico <code>models.py</code>.
</details>

<details>
<summary><b>¿Puedo usarlo con serializadores de DRF, Wagtail, Oscar o modelos base de terceros?</b></summary>
<br/>
Cualquier clase que parezca un modelo Django es detectada: subclases de <code>models.Model</code>, bases abstractas que empiezan con <code>Abstract</code>, mixins comunes que terminan en <code>Mixin</code> y nombres base conocidos como <code>TimeStampedModel</code> o <code>PolymorphicModel</code>. Las clases que no son modelos (<code>ModelAdmin</code>, <code>ModelSerializer</code>, <code>Form</code>, <code>View</code>, <code>Manager</code>, …) quedan filtradas.
</details>

<details>
<summary><b>¿Qué agentes de IA pueden usar el servidor MCP?</b></summary>
<br/>
Cualquier cliente compatible con MCP — Cursor, Aider, Continue.dev, Zed y cualquier otra herramienta que hable el protocolo. Simplemente apunta <code>command</code> al binario <code>django-orm-lens-mcp</code> instalado. Consulta la sección <a href="#-integrations">Integraciones</a>.
</details>

<details>
<summary><b>¿Hay una versión para JetBrains / PyCharm?</b></summary>
<br/>
Aún no. La ventana de herramientas Django Structure de PyCharm ya es buena, así que el diferencial de valor es menor. Si suficiente gente lo pide, se vuelve valioso hacerlo.
</details>

<br/>

## 🆘 Soporte

- 🐛 **Reportes de bugs** — [GitHub Issues](https://github.com/FROWNINGdev/django-orm-lens/issues) (por favor incluye un fragmento mínimo de `models.py`)
- 💡 **Solicitudes de funciones / ideas** — [GitHub Discussions](https://github.com/FROWNINGdev/django-orm-lens/discussions)
- 📝 **Reseñas en Marketplace** — [califica la extensión](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens&ssr=false#review-details) (la señal más rápida que mantiene este proyecto en movimiento)
- 🐍 **Página de PyPI** — [pypi.org/project/django-orm-lens](https://pypi.org/project/django-orm-lens/)
- 💚 **Patrocinar** — [github.com/sponsors/FROWNINGdev](https://github.com/sponsors/FROWNINGdev)

<br/>

## ✨ Contribuidores

Gracias a estas maravillosas personas ([clave de emojis](https://allcontributors.org/docs/en/emoji-key)) — todos los tipos de contribución cuentan, no solo el código. Traducciones, documentación, capturas de pantalla, reportes de bugs y preguntas respondidas son de primera clase.

¿Nuevo por aquí? Consulta [CONTRIBUTING.md → "How to become a contributor"](.github/CONTRIBUTING.md#how-to-become-a-contributor-all-skill-levels-welcome) y explora [`good first issue`](https://github.com/FROWNINGdev/django-orm-lens/labels/good%20first%20issue).

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/FROWNINGdev"><img src="https://avatars.githubusercontent.com/u/218313741?v=4?s=80" width="80px;" alt="frowningdev"/><br /><sub><b>frowningdev</b></sub></a><br /><a href="https://github.com/FROWNINGdev/django-orm-lens/commits?author=FROWNINGdev" title="Code">💻</a> <a href="#doc-FROWNINGdev" title="Documentation">📖</a> <a href="#design-FROWNINGdev" title="Design">🎨</a> <a href="#ideas-FROWNINGdev" title="Ideas, Planning, & Feedback">🤔</a> <a href="#maintenance-FROWNINGdev" title="Maintenance">🚧</a> <a href="#review-FROWNINGdev" title="Reviewed Pull Requests">👀</a> <a href="#test-FROWNINGdev" title="Tests">⚠️</a> <a href="#infra-FROWNINGdev" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/kingrubic"><img src="https://avatars.githubusercontent.com/u/116256161?v=4?s=80" width="80px;" alt="Bao"/><br /><sub><b>Bao</b></sub></a><br /><a href="https://github.com/FROWNINGdev/django-orm-lens/commits?author=kingrubic" title="Code">💻</a> <a href="#test-kingrubic" title="Tests">⚠️</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->
<!-- ALL-CONTRIBUTORS-LIST:END -->

Este proyecto sigue la especificación [all-contributors](https://allcontributors.org). Para ser añadido, comenta `@all-contributors please add @your-username for docs` (o `code`, `translation`, `design`, `ideas`, `question`, `bug`, `test`, `tutorial`, `example`, ...) en cualquier issue o PR.

<br/>

## 📜 Licencia

MIT © [FROWNINGdev](https://github.com/FROWNINGdev)

<br/>

<div align="center">

**Hecho para desarrolladores que se preocupan por su código base.**

[Marketplace](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens) · [PyPI](https://pypi.org/project/django-orm-lens/) · [GitHub](https://github.com/FROWNINGdev/django-orm-lens) · [Issues](https://github.com/FROWNINGdev/django-orm-lens/issues) · [Discussions](https://github.com/FROWNINGdev/django-orm-lens/discussions) · [Sponsor](https://github.com/sponsors/FROWNINGdev)

</div>
