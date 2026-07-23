import * as vscode from 'vscode';

/**
 * Django ORM Lens — file decorations for the sidebar tree.
 *
 * VS Code's `FileDecorationProvider` lets a tree item show a single-letter
 * badge plus a semantic colour on the right side of its row, without
 * altering the label. That's how the built-in Git integration shows `M`,
 * `U`, `D` next to files in the Explorer, and why users read it fluently
 * — the mechanic is baked into the platform.
 *
 * We reuse it here to surface CROSS-CUTTING model/field state:
 *
 *   - `!` (red)    — concerning: ForeignKey without on_delete,
 *                    CharField without max_length. Mirrors DOL013/DOL014.
 *   - `~` (yellow) — soft warning: null=True on a string-based field.
 *                    Mirrors DOL011.
 *
 * The decoration is opt-in per node: `treeProvider` sets `resourceUri` on
 * only those nodes we want decorated, using a synthetic `djangoOrmLens:`
 * URI whose query string encodes the state. That means the provider is
 * pure — it never reaches back into the tree state.
 *
 * URI shape: `djangoOrmLens:/<id-path>?flag=<state>`
 * where `<state>` is one of the constants below.
 */

export const DECORATION_SCHEME = 'djangoOrmLens';

export const FLAG_MISSING_ON_DELETE = 'missing-on-delete';
export const FLAG_MISSING_MAX_LENGTH = 'missing-max-length';
export const FLAG_NULL_ON_STRING = 'null-on-string';
export const FLAG_TEXTFIELD_MAX_LENGTH = 'textfield-max-length';

/**
 * Construct the synthetic resource URI for a tree node needing decoration.
 * Callers pass the node id (already stable across refreshes) and the flag.
 */
export function makeDecorationUri(nodeId: string, flag: string): vscode.Uri {
  // The path component must start with `/` for VS Code to accept the URI.
  return vscode.Uri.parse(
    `${DECORATION_SCHEME}:/${nodeId}?flag=${encodeURIComponent(flag)}`,
    true,
  );
}

interface DecorationRule {
  badge: string;
  color: vscode.ThemeColor;
  tooltip: string;
}

/** Static table — keeps semantics obvious and the provider trivially pure. */
const DECORATIONS: Record<string, DecorationRule> = {
  [FLAG_MISSING_ON_DELETE]: {
    badge: '!',
    color: new vscode.ThemeColor('errorForeground'),
    tooltip:
      'ForeignKey without on_delete — will raise TypeError at model-load (DOL013).',
  },
  [FLAG_MISSING_MAX_LENGTH]: {
    badge: '!',
    color: new vscode.ThemeColor('errorForeground'),
    tooltip:
      'CharField without max_length — will error at model-load (DOL014).',
  },
  [FLAG_NULL_ON_STRING]: {
    badge: '~',
    color: new vscode.ThemeColor('editorWarning.foreground'),
    tooltip:
      "null=True on a string-based field — Django recommends blank=True instead (DOL011).",
  },
  [FLAG_TEXTFIELD_MAX_LENGTH]: {
    badge: '~',
    color: new vscode.ThemeColor('editorWarning.foreground'),
    tooltip:
      'max_length on TextField has no DB effect (DOL015).',
  },
};

export class DjangoTreeDecorationProvider
  implements vscode.FileDecorationProvider {
  private _onDidChange = new vscode.EventEmitter<
    vscode.Uri | vscode.Uri[] | undefined
  >();
  readonly onDidChangeFileDecorations = this._onDidChange.event;

  provideFileDecoration(uri: vscode.Uri): vscode.FileDecoration | undefined {
    if (uri.scheme !== DECORATION_SCHEME) return undefined;
    const params = new URLSearchParams(uri.query);
    const flag = params.get('flag');
    if (!flag) return undefined;
    const rule = DECORATIONS[flag];
    if (!rule) return undefined;
    return {
      badge: rule.badge,
      color: rule.color,
      tooltip: rule.tooltip,
      // Propagate so decorated Fields also colour their parent Model row —
      // matches how Git decorations bubble up through the Explorer tree.
      propagate: true,
    };
  }

  /** Called when the underlying model changes so decorations refresh. */
  refresh(): void {
    this._onDidChange.fire(undefined);
  }
}
