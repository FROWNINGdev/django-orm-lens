[English](../../README.md) · **Русский** · [Español](./README.es.md) · [中文](./README.zh.md)

<div align="center">

<img src="media/hero.png" alt="Django ORM Lens — live sidebar and ER diagram for your Django models" width="100%"/>

<br/>
<br/>

# Django ORM Lens

### Смотрите всю схему Django целиком — в редакторе, в терминале и из вашего AI-агента.

Каждое приложение. Каждая модель. Каждое поле. Каждая связь. Сгруппировано, удобно навигируется и в одном нажатии от живой ER-диаграммы.

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

## 🎯 Выберите свой путь

Django ORM Lens поставляется как **три дистрибутива на одном ядре** — выберите тот, который подходит вашему рабочему процессу. Установка каждого занимает меньше 60 секунд.

**Пользователь редактора (VS Code / Cursor / Windsurf):** установите расширение → откройте любой Django-проект → в боковой панели появится дерево и ER-диаграмма.

```bash
code --install-extension frowningdev.django-orm-lens
```

**Пользователь терминала / CI:** установите с PyPI → запустите `django-orm-lens` в любой директории с Django-приложениями.

```bash
pip install django-orm-lens
django-orm-lens               # welcome + commands
django-orm-lens scan          # scan cwd for apps and models
```

**Пользователь AI-агентов для программирования (Cursor / Aider / Continue / Zed):** установите с extras для MCP → добавьте один JSON-блок в конфиг клиента.

```bash
pip install "django-orm-lens[mcp]"
```

Затем возьмите сниппет MCP-конфига из раздела [Интеграции](#-интеграции) ниже. Укажите в `DJANGO_ORM_LENS_ROOT` абсолютный путь к вашему Django-проекту.

---

## 📊 Трекшн

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

<sub><i>Обновлено 2026-07-19. Звёзды/форки на GitHub и суммарные загрузки (через pepy.tech) обновляются автоматически; недельные загрузки и версии VS Code / PyPI обновляются при релизе.</i></sub>

> Если инструмент сэкономил вам один `grep` при следующем погружении в незнакомый Django-проект — **[звёзды помогают другим найти его](https://github.com/FROWNINGdev/django-orm-lens/stargazers)**.

---

## ⚡ Установка

**VS Code / Cursor / Windsurf / любой форк Code:**

```bash
code --install-extension frowningdev.django-orm-lens
```

Или найдите **`Django ORM Lens`** во вкладке Extensions.

**Терминал и AI-агенты для программирования:**

```bash
pip install django-orm-lens              # CLI only
pip install "django-orm-lens[mcp]"       # + MCP server for AI agents
```

Требуется Python 3.9+. У CLI ноль runtime-зависимостей.

<br/>

## 🎯 Проблема

> **Работает офлайн. Работает на сломанном venv. Работает на чужом ноутбуке. Работает в CI.**

Вы открываете Django-проект. В нём 20 приложений. Нужно ответить на простой вопрос:

> _«В каком приложении живёт модель `Order` и как она связана с `User`?»_

Сегодня это значит: `Ctrl+P`, «models», прокрутить 30 совпадений, открыть пять файлов, `Ctrl+F` по `class Order`, продраться через 400 строк с `ForeignKey('otherapp.Something')` и попытаться вспомнить, что вы узнали два файла назад.

**Полдня. Каждый раз. На каждом проекте.**

<br/>

## ✨ С Django ORM Lens

<table>
<tr>
<td width="50%" valign="top">

### 📚 Дерево со всем сразу

Каждое приложение → каждая модель → каждое поле → каждая опция `Meta`. Сгруппировано по приложениям, отсортировано по алфавиту, разворачивается.

Иконки с первого взгляда отличают `CharField` от `ForeignKey` и от `ManyToManyField`.

</td>
<td width="50%" valign="top">

### 🕸️ Живая ER-диаграмма

Одной командой открывается Mermaid ER-диаграмма всей схемы. Она перерисовывается по мере редактирования. Экспорт в SVG.

`ForeignKey`, `OneToOneField` и `ManyToManyField` превращаются в правильные стрелки с кардинальностями.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🔎 Hover по связям

Наведите курсор на `ForeignKey('app.Model')` в любом Python-файле → всплывает карточка с полями целевой модели, её связями и ссылкой «Jump to». Никакого `Ctrl+F`, никаких диалогов выбора файла.

</td>
<td width="50%" valign="top">

### 🧭 Jump-to-definition

Клик по любому полю в дереве → курсор оказывается на нужной строке. Дерево фильтруется по имени приложения или модели. Полностью поддерживаются разнесённые пакеты `models/`.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### ⚡ Нулевая настройка

Никакого `DJANGO_SETTINGS_MODULE`. Никакого `runserver`. `models.py` парсится статически. Работает со сломанным venv, отсутствующей зависимостью или на чужом ноутбуке.

</td>
<td width="50%" valign="top">

### 🎨 Нативный UI VS Code

Тёмная тема. Светлая тема. Ваша тема. Следует вашей теме иконок, вашему шрифту, вашим горячим клавишам. Ничего кричащего, никакого брендинга.

</td>
</tr>
</table>

<br/>

## 📸 Как это выглядит

<div align="center">
<img src="media/hero.png" alt="Django ORM Lens sidebar showing an app's models with fields, relations, and Meta options" width="90%"/>
</div>

**Также входит в расширение:**

- 🕸️ **Живая ER-диаграмма** — стрелки кардинальностей Mermaid, подписи на рёбрах (`CASCADE`, `through Model`, `as related_name`), учёт темы, экспорт в SVG одним кликом
- 🔎 **Hover-карточки** — над любым `ForeignKey('app.Model')` или `ManyToManyField(...)`, со ссылкой для мгновенного перехода
- 🧭 **CodeLens** — над каждой строкой `class Model`: количество полей, количество связей и действие **Open ER diagram**
- 🎨 **Именованные темы** — `auto` / `default` / `dark` / `forest` / `neutral` для webview с диаграммой

<br/>

## 🤖 Для терминалов и AI-агентов программирования

Тот же парсер, что стоит в основе расширения для VS Code, поставляется как отдельный Python-пакет — с опциональным **MCP-сервером (Model Context Protocol)**, чтобы любой MCP-совместимый AI-агент мог перемещаться по вашей Django-схеме, не импортируя Django и не поднимая приложение.

### CLI

```bash
django-orm-lens scan -f json          # every app, every model, every field
django-orm-lens describe blog.Post    # one model in Markdown
django-orm-lens hover blog.Post       # compact hover card
django-orm-lens list | fzf            # flat app.Model — pipes anywhere
django-orm-lens er > schema.mmd       # Mermaid ER diagram
```

Каждая команда принимает `--path <dir>` и `--exclude <glob>`.

### MCP-сервер

Зарегистрируйте его один раз в своём агенте — и он предоставит пять read-only инструментов:

| Tool | Purpose |
| --- | --- |
| `list_apps` | Каждое Django-приложение в рабочей области с числом моделей |
| `list_models` | Плоский список `app.Model`, с опциональной фильтрацией по приложению |
| `describe_model` | Полное описание полей / связей / `Meta` одной модели |
| `find_relations` | Входящие и исходящие связи одной модели |
| `er_diagram` | Mermaid `erDiagram` для всей рабочей области |

```bash
# Start it directly
django-orm-lens-mcp

# Or via the CLI subcommand
django-orm-lens mcp
```

Установите `DJANGO_ORM_LENS_ROOT=/abs/path/to/project`, чтобы указать на любой проект.

<br/>

## 🔌 Интеграции

| Клиент | Как подключить | Статус |
|---|---|:-:|
| **VS Code** | `code --install-extension frowningdev.django-orm-lens` | ✅ |
| **Cursor** | тот же VSIX + опциональная MCP-запись в `~/.cursor/mcp.json` | ✅ |
| **Windsurf / VSCodium / любой форк Code** | установите VSIX с [Marketplace](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens) или из [GitHub Releases](https://github.com/FROWNINGdev/django-orm-lens/releases) | ✅ |
| **Aider** | добавьте `django-orm-lens-mcp` в свой `mcp.json` | ✅ (через MCP) |
| **Continue.dev** | зарегистрируйте MCP-сервер в `~/.continue/config.json` | ✅ (через MCP) |
| **Zed** | зарегистрируйте MCP-сервер в настройках Zed | ✅ (через MCP) |
| **Любой MCP-совместимый клиент** | укажите в `command` путь на `django-orm-lens-mcp`, задайте `DJANGO_ORM_LENS_ROOT` | ✅ |
| **Виден в [MCP Registry](https://registry.modelcontextprotocol.io/)** | официальный каталог серверов Model Context Protocol | ✅ |
| **Обычный терминал / CI** | `pip install django-orm-lens && django-orm-lens scan` | ✅ |

### Пример: Cursor / любой MCP-клиент

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

## 🚀 Быстрый старт (30 секунд)

**В VS Code:**

1. `code --install-extension frowningdev.django-orm-lens`
2. Откройте папку с `manage.py` или `models.py`
3. Кликните по иконке **Django ORM Lens** на панели активности
4. Разверните приложения → модели → поля
5. Кликните по иконке **type-hierarchy** в шапке панели → ER-диаграмма откроется рядом с кодом

**В терминале:**

```bash
pip install django-orm-lens
cd my-django-project
django-orm-lens scan -f table
```

**Как инструмент для AI-агента:**

```bash
pip install "django-orm-lens[mcp]"
```

…затем зарегистрируйте `django-orm-lens-mcp` в MCP-конфиге своего агента (см. таблицу [Интеграции](#-интеграции) выше).

Никаких окон настроек. Никакой регистрации. Никакой телеметрии.

<br/>

## 🎯 Для кого это

- **Django-разработчики**, попадающие в кодовую базу с 10+ приложениями и теряющиеся в разросшемся `models.py`.
- **Контрактники и фрилансеры**, которым нужно охватить незнакомый Django-проект за первый час, а не за первую неделю.
- **Команды при онбординге новых сотрудников**, желающие дать обзор схемы одним взглядом, без разворачивания инфраструктуры документации.
- **Продвинутые пользователи AI-агентов** (Cursor / Aider / Zed / Continue / любой MCP-совместимый клиент), которым нужно, чтобы агент точно отвечал на вопросы про схему — без выдачи ему учётных данных к БД и без запуска Django.
- **CI-пайплайны**, проверяющие форму схемы (например, «не сломали ли мы случайно `related_name`?»), не импортируя проект.
- **Соло-инди-разработчики** на сломанном venv или чужом ноутбуке — без `runserver`, без `manage.py migrate`, всё равно работает.

<br/>

## 🗺️ Позиционирование на рынке

Django ORM Lens находится на пересечении **инструментов для редакторов** и **инструментов для AI-агентов** — нишу, которую не закрывает ни один существующий пакет:

| Сегмент | Существующий вариант | Чего это стоит |
|---|---|---|
| Boot-and-graph | `django-extensions graph_models` | Требует Graphviz + настройки Django + рабочий URL БД |
| Веб-вьюер | `django-schema-graph` | Требует запущенный Django-сервер; ещё одна вещь, которая может сломаться |
| Админка | Django Admin | Требует runserver + аутентификацию + БД — хорошо для данных, не для архитектуры |
| Плагин к редактору | Django Structure в PyCharm | Только PyCharm; нет CLI, нет истории с AI-агентами |
| MCP-сервер | (до сих пор не существует) | AI-агенты угадывают вашу схему по исходникам, с ошибками |

**Django ORM Lens — единственный инструмент, поставляющий три поверхности из одного парсера:** расширение для VS Code (любой форк Code), CLI без зависимостей (терминалы + CI) и MCP-сервер (AI-агенты). Всё статически. Всё бесплатно. Всё под MIT.

<br/>

## 🤔 Чем это отличается?

| | **Django ORM Lens** | `django-extensions graph_models` | `django-schema-graph` | Django Admin | PyCharm Django Structure |
|---|:-:|:-:|:-:|:-:|:-:|
| Работает без загружаемого Django-проекта | ✅ | ❌ | ❌ | ❌ | ⚠️ |
| Zero-install (без graphviz, без сервера) | ✅ | ❌ | ❌ | ❌ | ❌ (нужен PyCharm) |
| Работает в VS Code / Cursor / любом форке Code | ✅ | ❌ | ❌ | ❌ | ❌ |
| Дерево в боковой панели редактора | ✅ | ❌ | ❌ | ❌ | ✅ |
| Живая ER-диаграмма | ✅ | ✅ | ✅ | ❌ | ❌ |
| Hover-карточки на `ForeignKey` | ✅ | ❌ | ❌ | ❌ | ⚠️ |
| CodeLens над классами моделей | ✅ | ❌ | ❌ | ❌ | ❌ |
| Поддержка разнесённого пакета `models/` | ✅ | ⚠️ | ⚠️ | ✅ | ✅ |
| CLI для терминала / CI | ✅ | ⚠️ | ❌ | ❌ | ❌ |
| MCP-сервер для AI-агентов | ✅ | ❌ | ❌ | ❌ | ❌ |
| Виден в [MCP Registry](https://registry.modelcontextprotocol.io/) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Бесплатный и open-source (MIT) | ✅ | ✅ | ✅ | ✅ | ❌ (платная IDE) |
| Поддержка версий Django | **4.0 – 5.2** | последняя | 3.2 – 4.1 (не обновляется с 2023) | последняя | последняя |

> *`django-schema-graph` не обновлялся с мая 2023 и не тестируется на Django 5.x.*

<br/>

## ⚙️ Конфигурация

Дефолты продуманы и разумны. Если нужно подкрутить:

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

| Настройка | Тип | По умолчанию | Что делает |
|---|---|---|---|
| `djangoOrmLens.excludeGlobs` | `string[]` | См. выше | Glob-паттерны, которые пропускаются при сканировании |
| `djangoOrmLens.autoRefresh` | `boolean` | `true` | Повторное сканирование при изменениях `models.py` |

<br/>

## 🧭 Команды

Откройте палитру команд (`Ctrl+Shift+P` / `Cmd+Shift+P`) и введите «Django ORM Lens»:

| Команда | Что делает |
|---|---|
| `Django ORM Lens: Refresh` | Принудительное пересканирование рабочей области |
| `Django ORM Lens: Show ER Diagram` | Открыть Mermaid ER-диаграмму рядом с кодом |
| `Django ORM Lens: Filter Models` | Отфильтровать дерево по имени приложения / модели / поля |
| `Django ORM Lens: Clear Filter` | Восстановить полное дерево |
| `Django ORM Lens: Jump to Model` | Программная — вызывается кликами по дереву и hover-карточкам |

<br/>

## 🗺️ Дорожная карта

**Выпущено**

- [x] Дерево в боковой панели, сгруппированное по приложениям
- [x] Живая Mermaid ER-диаграмма
- [x] Hover-карточки над `ForeignKey('app.Model')`
- [x] Фильтр дерева по имени
- [x] Поддержка разнесённого пакета `models/`
- [x] Экспорт ER-диаграммы в SVG
- [x] Python CLI + MCP-сервер для терминалов и AI-агентов
- [x] Welcome-вью для пустых рабочих областей
- [x] Безопасный по путям jump-to-definition и санитизированный hover-markdown
- [x] **v0.3.0** — CodeLens над каждым классом модели (`N fields · N relations · Open ER diagram`)
- [x] **v0.3.0** — Подписи на рёбрах диаграммы (`CASCADE`, `SET_NULL`, `PROTECT`, `related_name`)
- [x] **v0.3.0** — Именованные цветовые темы (`auto` / `default` / `dark` / `forest` / `neutral`)
- [x] **v0.3.1** — `through_model` на M2M-рёбрах (контрибьютор — [@kingrubic](https://github.com/kingrubic))
- [x] **v0.3.1** — Добавлено в [официальный MCP Registry](https://registry.modelcontextprotocol.io/) + [Glama.ai](https://glama.ai/mcp/servers/FROWNINGdev/django-orm-lens)

**Ближайшее**

- [ ] Зум + миникарта + авто-раскладка внутри webview ([#4](https://github.com/FROWNINGdev/django-orm-lens/issues/4))
- [ ] Автодополнение ORM-запросов внутри `.filter()` / `.exclude()` / `.annotate()` ([#3](https://github.com/FROWNINGdev/django-orm-lens/issues/3))
- [ ] Чекбоксы включения/выключения приложений / моделей — чтобы разгрузить огромные схемы

**Позже**

- [ ] Граф зависимостей миграций
- [ ] Поддержка сторонних полей (`django-mptt`, `django-taggit`, `django-model-utils`)
- [ ] Плагин для JetBrains / PyCharm (если будет спрос)

Голосуйте, ставя 👍 на соответствующий [issue](https://github.com/FROWNINGdev/django-orm-lens/issues).

<br/>

## ❓ FAQ

<details>
<summary><b>Отправляете ли вы мой код на сервер?</b></summary>
<br/>
Нет. Каждый байт остаётся на вашей машине. Парсер — это чистый TypeScript (расширение) или чистый Python (CLI). Никаких вызовов LLM, никакой телеметрии, никакой аналитики, никаких отчётов об ошибках. Mermaid-рендерер работает внутри sandbox-webview VS Code.
</details>

<details>
<summary><b>Работает ли это с Poetry / uv / conda / вообще без venv?</b></summary>
<br/>
Да. Расширение читает исходники Python напрямую — оно не импортирует Django и ему всё равно, каким пакетным менеджером вы пользуетесь. Для CLI нужен только Python 3.9+.
</details>

<details>
<summary><b>Мои модели разбиты по нескольким файлам внутри пакета <code>models/</code>. Это поддерживается?</b></summary>
<br/>
Да, начиная с v0.2.0. И расширение, и CLI обходят <code>models/*.py</code> наряду с классическим <code>models.py</code>.
</details>

<details>
<summary><b>Можно ли использовать это с DRF-сериализаторами, Wagtail, Oscar или сторонними базовыми моделями?</b></summary>
<br/>
Подхватывается любой класс, похожий на Django-модель: подклассы <code>models.Model</code>, абстрактные базы, начинающиеся с <code>Abstract</code>, распространённые миксины, оканчивающиеся на <code>Mixin</code>, и известные базовые имена вроде <code>TimeStampedModel</code> или <code>PolymorphicModel</code>. Неподходящие классы (<code>ModelAdmin</code>, <code>ModelSerializer</code>, <code>Form</code>, <code>View</code>, <code>Manager</code>, …) отфильтровываются.
</details>

<details>
<summary><b>Какие AI-агенты могут использовать MCP-сервер?</b></summary>
<br/>
Любой MCP-совместимый клиент — Cursor, Aider, Continue.dev, Zed и любой другой инструмент, поддерживающий протокол. Просто укажите в <code>command</code> путь к установленному бинарнику <code>django-orm-lens-mcp</code>. См. раздел <a href="#-интеграции">Интеграции</a>.
</details>

<details>
<summary><b>Есть ли версия для JetBrains / PyCharm?</b></summary>
<br/>
Пока нет. Инструмент Django Structure в PyCharm сам по себе неплох, поэтому потенциальный прирост ценности меньше. Если попросит достаточно людей — сделать станет оправданно.
</details>

<br/>

## 🆘 Поддержка

- 🐛 **Баг-репорты** — [GitHub Issues](https://github.com/FROWNINGdev/django-orm-lens/issues) (пожалуйста, приложите минимальный сниппет `models.py`)
- 💡 **Фичи и идеи** — [GitHub Discussions](https://github.com/FROWNINGdev/django-orm-lens/discussions)
- 📝 **Отзывы в Marketplace** — [оцените расширение](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens&ssr=false#review-details) (самый быстрый сигнал, поддерживающий проект живым)
- 🐍 **Страница на PyPI** — [pypi.org/project/django-orm-lens](https://pypi.org/project/django-orm-lens/)
- 💚 **Спонсорство** — [github.com/sponsors/FROWNINGdev](https://github.com/sponsors/FROWNINGdev)

<br/>

## ✨ Контрибьюторы

Спасибо этим замечательным людям ([расшифровка эмодзи](https://allcontributors.org/docs/en/emoji-key)) — учитываются все виды вклада, не только код. Переводы, документация, скриншоты, баг-репорты и ответы на вопросы — всё это равноценно.

Впервые здесь? Загляните в [CONTRIBUTING.md → «How to become a contributor»](.github/CONTRIBUTING.md#how-to-become-a-contributor-all-skill-levels-welcome) и посмотрите [`good first issue`](https://github.com/FROWNINGdev/django-orm-lens/labels/good%20first%20issue).

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

Проект следует спецификации [all-contributors](https://allcontributors.org). Чтобы попасть в список, оставьте комментарий `@all-contributors please add @your-username for docs` (или `code`, `translation`, `design`, `ideas`, `question`, `bug`, `test`, `tutorial`, `example`, ...) на любом issue или PR.

<br/>

## 📜 Лицензия

MIT © [FROWNINGdev](https://github.com/FROWNINGdev)

<br/>

<div align="center">

**Сделано для разработчиков, которым не всё равно на свою кодовую базу.**

[Marketplace](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens) · [PyPI](https://pypi.org/project/django-orm-lens/) · [GitHub](https://github.com/FROWNINGdev/django-orm-lens) · [Issues](https://github.com/FROWNINGdev/django-orm-lens/issues) · [Discussions](https://github.com/FROWNINGdev/django-orm-lens/discussions) · [Sponsor](https://github.com/sponsors/FROWNINGdev)

</div>
