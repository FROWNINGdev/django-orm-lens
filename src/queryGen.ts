import { ParsedField, ParsedModel, WorkspaceIndex } from './types';

/**
 * Interactive Query Builder — pure template engine.
 *
 * Turn a click on a field or model in the tree/ER-diagram into a Django
 * ORM snippet. No `vscode` dependency here: the engine consumes the
 * existing parser types and returns strings the VS Code layer inserts
 * as a `SnippetString` (when there is an active editor) or drops into
 * a new untitled buffer.
 *
 * Design distilled from proven prior art (research-first):
 *
 *   - DataGrip / DBeaver → right-click submenu → live preview drawer.
 *     Output goes into an editable buffer, never silently to clipboard.
 *   - Prisma Studio      → best filter UX; worst code export. Their gap
 *                          is the code-generation surface — fills it.
 *   - django-silk        → cluster N+1: when the user picks a template
 *                          on an FK field, we automatically suggest a
 *                          companion `.select_related(...)` line.
 *   - Django docs        → grammar gotchas we MUST respect:
 *                          `filter(a=1).filter(b=2) != filter(a=1, b=2)`
 *                          across a multi-valued relation.
 *                          `.values().distinct()` ordering matters.
 *                          `related_name` overrides the reverse accessor.
 *
 * Public API: `generateQueryTemplates(target, index)` returns an ordered
 * array of `QueryTemplate` describing the buttons the UI should show.
 * Each carries a pre-rendered snippet with VS Code tab-stop placeholders.
 *
 * Callers:
 *   - `src/extension.ts` — `djangoOrmLens.buildQuery` command handler
 *   - `test/query-gen.test.js` — pure snapshot tests
 */

/** Where the user clicked. */
export type QueryTarget =
  | {
      kind: 'field';
      appName: string;
      modelName: string;
      fieldName: string;
    }
  | {
      kind: 'model';
      appName: string;
      modelName: string;
    };

export interface QueryTemplate {
  /** Menu-facing title, shown in the QuickPick. */
  title: string;
  /** One-line explainer. Shown as QuickPick description. */
  description: string;
  /**
   * The rendered snippet. Placeholders use VS Code snippet syntax
   * (`${1:value}`) so the SnippetString wire tab-stops correctly.
   */
  snippet: string;
  /** Category tag for grouping in the UI. */
  category: 'filter' | 'perf' | 'aggregate' | 'projection';
}

/* ---------------------------  helpers  ------------------------------- */

function findModel(
  index: WorkspaceIndex,
  appName: string,
  modelName: string,
): ParsedModel | undefined {
  for (const app of index.apps) {
    if (app.name !== appName) continue;
    for (const m of app.models) if (m.name === modelName) return m;
  }
  return undefined;
}

function findField(
  model: ParsedModel,
  fieldName: string,
): ParsedField | undefined {
  return model.fields.find((f) => f.name === fieldName);
}

/**
 * Compute the reverse-accessor name a related model would use to point
 * back at `owner`. Honours `related_name`; falls back to Django's
 * `<lowercase-model-name>_set`.
 */
function reverseAccessorName(
  ownerModelName: string,
  fkField: ParsedField,
): string {
  if (fkField.relatedName) return fkField.relatedName;
  return `${ownerModelName.toLowerCase()}_set`;
}

/** Build a VS Code snippet tab-stop placeholder. */
function snip(placeholder: string, tabStop: number, defaultValue = ''): string {
  const safe = defaultValue.replace(/\$/g, '\\$').replace(/\}/g, '\\}');
  return safe
    ? `\${${tabStop}:${safe}}`
    : `\${${tabStop}:${placeholder}}`;
}

function isRelationField(f: ParsedField): boolean {
  return !!f.isRelation;
}

/* ------------------------  template builders  ------------------------ */

/** Basic `.filter(field=<value>)` — the workhorse. */
function templateFilterField(
  model: ParsedModel,
  field: ParsedField,
  index: WorkspaceIndex,
): QueryTemplate {
  const qs = `${model.name}.objects.filter(${field.name}=${snip('value', 1)})`;
  // Companion select_related when the field is an FK — django-silk lesson.
  let extra = '';
  if (
    field.isRelation &&
    (field.relationKind === 'ForeignKey' ||
      field.relationKind === 'OneToOneField') &&
    field.relatedModel
  ) {
    void findModel(index, model.appName, field.relatedModel);
    extra = `.select_related('${field.name}')`;
  }
  return {
    title: `.filter(${field.name}=…)`,
    description: field.isRelation
      ? 'Filter by this relation; adds select_related to avoid N+1'
      : `Filter by ${field.type}`,
    snippet: `${qs}${extra}`,
    category: 'filter',
  };
}

/** `.select_related('fk')` — for FK / O2O. Focused N+1 fix. */
function templateSelectRelated(
  model: ParsedModel,
  field: ParsedField,
): QueryTemplate {
  return {
    title: `.select_related('${field.name}')`,
    description: 'Single JOIN — kills N+1 for this FK',
    snippet: `${model.name}.objects.all().select_related('${field.name}')`,
    category: 'perf',
  };
}

/** `.prefetch_related('m2m')` — for M2M and reverse FK. */
function templatePrefetchRelated(
  model: ParsedModel,
  field: ParsedField,
): QueryTemplate {
  return {
    title: `.prefetch_related('${field.name}')`,
    description: 'Batch fetch — kills N+1 for this M2M/reverse relation',
    snippet: `${model.name}.objects.all().prefetch_related('${field.name}')`,
    category: 'perf',
  };
}

/**
 * `.annotate(count=Count('reverse_accessor__pk'))` — for reverse FKs.
 * We look up any FK on other models that points at this one and offer
 * to count via its reverse accessor.
 */
function templateAnnotateCountReverse(
  model: ParsedModel,
  index: WorkspaceIndex,
): QueryTemplate[] {
  const out: QueryTemplate[] = [];
  for (const app of index.apps) {
    for (const other of app.models) {
      if (other === model) continue;
      for (const f of other.fields) {
        if (!isRelationField(f)) continue;
        if (f.relatedModel !== model.name) continue;
        if (f.relationKind !== 'ForeignKey' && f.relationKind !== 'ManyToManyField')
          continue;
        const accessor = reverseAccessorName(other.name, f);
        const shortName = accessor.replace(/_set$/, '');
        out.push({
          title: `.annotate(${shortName}_count=Count('${accessor}'))`,
          description: `Count ${other.appName}.${other.name} rows pointing here`,
          snippet: `${model.name}.objects.annotate(${shortName}_count=Count('${accessor}')).order_by('-${shortName}_count')`,
          category: 'aggregate',
        });
      }
    }
  }
  return out;
}

/** `.values('field').distinct()` — distinct values of one column. */
function templateDistinctValues(
  model: ParsedModel,
  field: ParsedField,
): QueryTemplate {
  return {
    title: `.values('${field.name}').distinct()`,
    description: `Return distinct ${field.type} values`,
    snippet: `${model.name}.objects.values('${field.name}').distinct()`,
    category: 'projection',
  };
}

/** `.only('field', ...)` — column pruning shortcut. */
function templateOnly(
  model: ParsedModel,
  field: ParsedField,
): QueryTemplate {
  return {
    title: `.only('${field.name}')`,
    description: 'Load just this column — cheaper on wide tables',
    snippet: `${model.name}.objects.only('${field.name}', ${snip('extra_field', 1)})`,
    category: 'projection',
  };
}

/* ---------------------------  public API  ---------------------------- */

/**
 * Return the ordered list of applicable templates for the click target.
 * Order is: filter → perf → aggregate → projection, matching how users
 * mentally build queries ("filter first, then optimise, then aggregate,
 * then project").
 */
export function generateQueryTemplates(
  target: QueryTarget,
  index: WorkspaceIndex,
): QueryTemplate[] {
  const model = findModel(index, target.appName, target.modelName);
  if (!model) return [];

  const out: QueryTemplate[] = [];

  if (target.kind === 'field') {
    const field = findField(model, target.fieldName);
    if (!field) return [];
    out.push(templateFilterField(model, field, index));
    if (
      field.isRelation &&
      (field.relationKind === 'ForeignKey' ||
        field.relationKind === 'OneToOneField')
    ) {
      out.push(templateSelectRelated(model, field));
    }
    if (field.isRelation && field.relationKind === 'ManyToManyField') {
      out.push(templatePrefetchRelated(model, field));
    }
    out.push(templateDistinctValues(model, field));
    out.push(templateOnly(model, field));
    return sortByCategory(out);
  }

  // target.kind === 'model'
  out.push({
    title: `.objects.all()`,
    description: 'The base QuerySet',
    snippet: `${model.name}.objects.all()`,
    category: 'projection',
  });
  // Suggest reverse-FK count annotations if any inbound FKs exist.
  out.push(...templateAnnotateCountReverse(model, index));
  return sortByCategory(out);
}

const CATEGORY_ORDER: Record<QueryTemplate['category'], number> = {
  filter: 0,
  perf: 1,
  aggregate: 2,
  projection: 3,
};

function sortByCategory(templates: QueryTemplate[]): QueryTemplate[] {
  return templates
    .slice()
    .sort((a, b) => CATEGORY_ORDER[a.category] - CATEGORY_ORDER[b.category]);
}

/**
 * Convenience for tests and CLI parity: render a template as a plain
 * Python string with tab-stops resolved to their default values.
 */
export function snippetToPython(snippet: string): string {
  return snippet.replace(/\$\{(\d+):([^}]*)\}/g, (_m, _n, defaultValue) => {
    return defaultValue.replace(/\\\}/g, '}').replace(/\\\$/g, '$');
  });
}
