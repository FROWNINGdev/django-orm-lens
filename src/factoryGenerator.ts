import { ParsedField, ParsedModel, WorkspaceIndex } from './types';

/**
 * Factory generator — turn a `ParsedModel` into a factory_boy scaffold.
 *
 * factory_boy is the canonical test-fixture library in the Django world:
 * ~4M downloads/month on PyPI, first-class docs on the Django site. Users
 * hate writing the boilerplate; every model needs a factory, and every
 * factory needs Faker providers keyed by field type.
 *
 * We produce a string of Python code with:
 *
 *   - a `factory` + `factory_boy` + `faker` import shim
 *   - one `DjangoModelFactory` subclass per target model
 *   - a Faker provider chosen per field type (see `providerFor`)
 *   - SubFactory references for FKs pointing at other models we know about
 *   - a `post_generation` hook for M2M with a `through` model
 *
 * The result is opened as an untitled document — the user reviews, edits,
 * and saves wherever their team prefers (`app/factories.py`, `conftest.py`,
 * a dedicated `tests/factories/` package).
 *
 * Public API: `generateFactoryCode(model, index)` returns Python source.
 * Callers: `src/extension.ts` command handler + `codeLensProvider.ts`
 * CodeLens above each model class + tree context menu.
 */

/** Map a Django field type to a Faker provider expression. */
function providerFor(field: ParsedField): string {
  const t = field.type;
  // Choices in `args` (e.g. `choices=STATUS_CHOICES`) — favour the choices.
  if (/\bchoices\s*=/.test(field.args)) {
    return `factory.Iterator([...])  # TODO: fill from ${extractChoiceName(field.args) ?? 'choices'}`;
  }

  switch (t) {
    case 'EmailField':
      return "factory.Faker('email')";
    case 'URLField':
      return "factory.Faker('url')";
    case 'SlugField':
      return "factory.Faker('slug')";
    case 'UUIDField':
      return 'factory.Faker(\'uuid4\')';
    case 'IPAddressField':
    case 'GenericIPAddressField':
      return "factory.Faker('ipv4')";
    case 'BooleanField':
    case 'NullBooleanField':
      return "factory.Faker('pybool')";
    case 'DateField':
      return "factory.Faker('date_object')";
    case 'DateTimeField':
      return "factory.Faker('date_time', tzinfo=timezone.utc)";
    case 'TimeField':
      return "factory.Faker('time_object')";
    case 'DurationField':
      return "datetime.timedelta(days=1)";
    case 'JSONField':
      return "factory.Dict({})";
    case 'BinaryField':
      return "b''";
    case 'FileField':
      return "factory.django.FileField(filename='sample.txt')";
    case 'ImageField':
      return "factory.django.ImageField(color='blue')";
    case 'FilePathField':
      return "factory.Faker('file_path')";
    case 'DecimalField': {
      const maxDigits = matchIntKwarg(field.args, 'max_digits') ?? 10;
      const decimalPlaces = matchIntKwarg(field.args, 'decimal_places') ?? 2;
      return `factory.Faker('pydecimal', left_digits=${
        maxDigits - decimalPlaces
      }, right_digits=${decimalPlaces})`;
    }
    case 'FloatField':
      return "factory.Faker('pyfloat')";
    case 'IntegerField':
    case 'SmallIntegerField':
    case 'BigIntegerField':
    case 'PositiveIntegerField':
    case 'PositiveSmallIntegerField':
    case 'PositiveBigIntegerField': {
      const isPositive = t.startsWith('Positive');
      const min = isPositive ? 0 : -1000;
      return `factory.Faker('random_int', min=${min}, max=1000)`;
    }
    case 'AutoField':
    case 'BigAutoField':
    case 'SmallAutoField':
      // factory_boy leaves auto-pk to the DB; skip.
      return '';
    case 'CharField': {
      const maxLen = matchIntKwarg(field.args, 'max_length') ?? 100;
      if (maxLen <= 20) return `factory.Faker('word')`;
      if (maxLen <= 80) return `factory.Faker('sentence', nb_words=4)`;
      return `factory.Faker('sentence', nb_words=10)`;
    }
    case 'TextField':
      return "factory.Faker('paragraph')";
  }

  // GeoDjango types
  if (/^Point/.test(t) || /^Polygon/.test(t) || /^LineString/.test(t)) {
    return "None  # TODO: build a valid GeoDjango geometry";
  }

  // Fallback for anything unknown.
  return `factory.Faker('word')  # TODO: replace with a suitable provider for ${t}`;
}

/** Extract `choices=SOMETHING`, return `SOMETHING` or undefined. */
function extractChoiceName(args: string): string | undefined {
  const m = /\bchoices\s*=\s*([A-Za-z_][\w.]*)/.exec(args);
  return m?.[1];
}

function matchIntKwarg(args: string, name: string): number | undefined {
  const re = new RegExp(`\\b${name}\\s*=\\s*(\\d+)`);
  const m = re.exec(args);
  return m ? parseInt(m[1], 10) : undefined;
}

/** Find a ParsedModel by its short or dotted name in the index. */
function findModelByRef(index: WorkspaceIndex, ref: string): ParsedModel | undefined {
  if (!ref) return undefined;
  const dotted = ref.split('.');
  const short = dotted[dotted.length - 1];
  for (const app of index.apps) {
    for (const model of app.models) {
      if (model.name === short) return model;
    }
  }
  return undefined;
}

/**
 * Produce the factory class body for one model. Returns Python source (no
 * imports; the caller aggregates imports once at the top of the output).
 */
function factoryClassFor(
  model: ParsedModel,
  index: WorkspaceIndex,
  emitted: Set<string>,
  pending: ParsedModel[],
): string {
  const factoryName = `${model.name}Factory`;
  const lines: string[] = [];
  lines.push(`class ${factoryName}(factory.django.DjangoModelFactory):`);
  lines.push(`    class Meta:`);
  lines.push(`        model = ${model.name}`);
  lines.push('');

  const postM2m: string[] = [];

  for (const field of model.fields) {
    if (field.type === 'AutoField' || field.type === 'BigAutoField' || field.type === 'SmallAutoField') {
      continue;
    }

    if (field.isRelation) {
      const relatedModel = findModelByRef(index, field.relatedModel ?? '');
      if (field.relationKind === 'ForeignKey' || field.relationKind === 'OneToOneField') {
        const ref = relatedModel ? `${relatedModel.name}Factory` : "'self'";
        if (relatedModel && !emitted.has(relatedModel.name) && relatedModel !== model) {
          pending.push(relatedModel);
        }
        lines.push(`    ${field.name} = factory.SubFactory(${ref})`);
      } else if (field.relationKind === 'ManyToManyField') {
        // M2M — must be added post-generation.
        postM2m.push(field.name);
      }
      continue;
    }

    const provider = providerFor(field);
    if (!provider) continue;
    lines.push(`    ${field.name} = ${provider}`);
  }

  if (postM2m.length) {
    lines.push('');
    lines.push(`    @factory.post_generation`);
    lines.push(`    def _add_m2m(self, create, extracted, **kwargs):`);
    lines.push(`        if not create:`);
    lines.push(`            return`);
    for (const name of postM2m) {
      lines.push(
        `        if extracted and '${name}' in extracted:`,
      );
      lines.push(`            for item in extracted['${name}']:`);
      lines.push(`                self.${name}.add(item)`);
    }
  }

  return lines.join('\n');
}

/** Assemble the full output document. */
export function generateFactoryCode(
  model: ParsedModel,
  index: WorkspaceIndex,
): string {
  const emitted = new Set<string>();
  const pending: ParsedModel[] = [model];
  const factories: string[] = [];

  while (pending.length > 0) {
    const next = pending.shift()!;
    if (emitted.has(next.name)) continue;
    emitted.add(next.name);
    factories.push(factoryClassFor(next, index, emitted, pending));
  }

  const importedModelNames = [...emitted].join(', ');
  const header = [
    '"""',
    `Auto-generated by Django ORM Lens from ${model.appName}.${model.name}.`,
    '',
    'Review each factory before committing:',
    '  - swap Faker providers for choices/enums where appropriate',
    '  - narrow the Meta.model import path to the real app label',
    '  - decide whether M2M fields want post_generation or Trait',
    '',
    'Install: pip install factory-boy faker',
    '"""',
    '',
    'import datetime',
    'from datetime import timezone',
    '',
    'import factory',
    '',
    `# TODO: adjust the import path to your project layout.`,
    `from ${model.appName}.models import ${importedModelNames}`,
    '',
    '',
  ].join('\n');

  return header + factories.join('\n\n\n') + '\n';
}
