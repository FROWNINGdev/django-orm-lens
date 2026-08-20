/**
 * Which `message` events an ER-diagram webview is allowed to act on.
 *
 * This lives outside `src/webview/` on purpose. That directory is excluded
 * from `tsc` (see tsconfig `exclude`) because esbuild bundles it separately,
 * so nothing in it reaches `out/` and nothing in it can be required by a test.
 * The guard reported in #55 stood wrong from the first React Flow build until
 * it was measured precisely because it had no test that could run without a
 * browser and a VS Code host; keeping the policy here, importable from both
 * sides, is what makes that test possible.
 *
 * The rule itself: compare `origin`, not `source`. Measured on a real panel, a
 * legitimate `index` push from the extension host arrives with a `source` that
 * matches neither `window` nor `window.parent`, so a source check drops every
 * message and an open panel silently stops updating. `origin === window.origin`
 * is what the VS Code maintainers recommend over hardcoding `vscode-webview:`,
 * whose scheme differs between desktop and vscode.dev.
 * https://github.com/microsoft/vscode-discussions/discussions/1061
 */

/** The message types the extension host is allowed to send inward. */
export const EXTENSION_MESSAGE_TYPES = ['index', 'theme'] as const;

export type ExtensionMessageType = (typeof EXTENSION_MESSAGE_TYPES)[number];

/** The parts of a `MessageEvent` the policy reads. */
export interface IncomingMessage {
  origin?: unknown;
  data?: unknown;
}

/**
 * True when `event` came from this webview's own origin and carries a payload
 * shaped like one of the messages the host actually sends.
 *
 * `selfOrigin` is passed in rather than read off a global so the policy stays
 * a pure function — the whole point of the file.
 */
export function acceptsMessage(
  event: IncomingMessage | null | undefined,
  selfOrigin: string
): boolean {
  if (!event) return false;
  if (event.origin !== selfOrigin) return false;
  const data = event.data;
  if (!data || typeof data !== 'object') return false;
  const type = (data as { type?: unknown }).type;
  return (
    typeof type === 'string' && (EXTENSION_MESSAGE_TYPES as readonly string[]).includes(type)
  );
}
