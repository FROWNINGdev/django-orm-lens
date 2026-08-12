/**
 * Ask for a GitHub star — once, late, and only after the tool has been useful.
 *
 * Why this exists
 * ---------------
 * Measured 2026-08-12: 62 Marketplace installs against 61 GitHub stars, and
 * three referrals from the repo's largest social channel in fourteen days.
 * Installs overtaking stars is the signal: people find the extension in the
 * Marketplace, use it, and never visit the repository. The ask was missing
 * entirely, so its conversion was not low — it was zero by construction.
 *
 * Design constraints, in order of how easy they are to get wrong:
 *
 * 1. **Never on install.** A prompt that appears before the tool has done
 *    anything is dismissed reflexively, and that dismissal is permanent in
 *    the user's mind even when it isn't in ours. The counter keys off opening
 *    the ER diagram, which is the moment the extension has visibly produced
 *    something.
 * 2. **"Later" is not "no".** Conflating them either nags someone who said no
 *    or silently drops someone who was merely busy. They are separate states.
 * 3. **Two prompts, lifetime maximum.** After a deferral the ask re-arms once,
 *    far out. If it is ignored a second time, that is an answer.
 *
 * The decision is a pure function so it can be tested without a VS Code host;
 * everything touching `vscode` is confined to `maybeAskForStar`.
 */

import * as vscode from 'vscode';

export const REPO_URL = 'https://github.com/FROWNINGdev/django-orm-lens';

const KEY_OPENS = 'djangoOrmLens.star.opens';
const KEY_DISMISSED_AT = 'djangoOrmLens.star.dismissedAt';
const KEY_SILENCED = 'djangoOrmLens.star.silenced';

/** First ask: the third time the user opens the diagram. */
export const FIRST_PROMPT_AT = 3;
/** Second and final ask: this many further opens after a deferral. */
export const REPEAT_AFTER = 12;

export interface StarPromptState {
  /** How many times the ER diagram has been opened, all time. */
  opens: number;
  /** `opens` at the moment the user chose "Later", or null if never. */
  dismissedAt: number | null;
  /** User declined permanently, or already acted on the ask. */
  silenced: boolean;
}

/**
 * Should the ask be shown for this state? Pure — no I/O, no vscode.
 *
 * Deliberately evaluated *after* the counter is incremented, so `opens` is the
 * number of diagrams the user has actually seen, not the number they had seen
 * before this one.
 */
export function shouldPrompt(
  state: StarPromptState,
  firstAt: number = FIRST_PROMPT_AT,
  repeatAfter: number = REPEAT_AFTER
): boolean {
  if (state.silenced) return false;
  if (state.dismissedAt === null) return state.opens >= firstAt;
  return state.opens >= state.dismissedAt + repeatAfter;
}

export function readState(context: vscode.ExtensionContext): StarPromptState {
  return {
    opens: context.globalState.get<number>(KEY_OPENS, 0),
    dismissedAt: context.globalState.get<number | null>(KEY_DISMISSED_AT, null),
    silenced: context.globalState.get<boolean>(KEY_SILENCED, false),
  };
}

/**
 * Count one diagram open and, if this is the moment, ask.
 *
 * Never throws into the caller: this runs on a UI path that must keep working
 * if globalState is unavailable or the user's VS Code build returns something
 * unexpected from `showInformationMessage`. A broken nag must not break the
 * feature it is attached to.
 */
export async function maybeAskForStar(
  context: vscode.ExtensionContext
): Promise<void> {
  try {
    const previous = readState(context);
    if (previous.silenced) return; // cheapest exit — no write, no work

    const opens = previous.opens + 1;
    await context.globalState.update(KEY_OPENS, opens);

    const state: StarPromptState = { ...previous, opens };
    if (!shouldPrompt(state)) return;

    const star = 'Star on GitHub';
    const later = 'Later';
    const never = "Don't ask again";
    const choice = await vscode.window.showInformationMessage(
      'Django ORM Lens is free and MIT-licensed. If it saved you time, a star helps another Django developer find it.',
      star,
      later,
      never
    );

    if (choice === star) {
      await vscode.env.openExternal(vscode.Uri.parse(REPO_URL));
      await context.globalState.update(KEY_SILENCED, true);
    } else if (choice === never) {
      await context.globalState.update(KEY_SILENCED, true);
    } else {
      // "Later" *and* dismissal-by-closing land here. Both mean "not now";
      // neither means "no". Record where we were so the single re-ask lands
      // far from here, and silence it permanently if this was already the
      // second time.
      if (state.dismissedAt === null) {
        await context.globalState.update(KEY_DISMISSED_AT, opens);
      } else {
        await context.globalState.update(KEY_SILENCED, true);
      }
    }
  } catch {
    // Intentionally swallowed — see the doc comment above.
  }
}
