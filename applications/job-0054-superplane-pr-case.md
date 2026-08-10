# SuperPlane PR investigation case

Date: 2026-08-10
Related application: `job-0054` — SuperPlane Product Engineer
Target repository: https://github.com/superplanehq/superplane

## Context

SuperPlane requires every applicant to submit at least one pull request to `superplanehq/superplane` before applying. The PR can be small and does not need to be merged.

The initial candidate was issue #6618, a React/Radix Select controlled/uncontrolled warning in `FactoryLineStepEditor.tsx`:

- Issue: https://github.com/superplanehq/superplane/issues/6618
- File: `web_src/src/pages/factories/FactoryLineStepEditor.tsx`

The original code converts the draft's empty-string values into `undefined`:

```tsx
<Select
  value={step.appId || undefined}
  onValueChange={(appId) => onChange({ ...step, appId, entrypoint: "" })}
>

<Select
  value={step.entrypoint || undefined}
  onValueChange={(entrypoint) => onChange({ ...step, entrypoint })}
>
```

`DraftStep.appId` and `DraftStep.entrypoint` are string fields and use `""` as their empty state. Radix Select treats `undefined` as uncontrolled, so this causes the component to switch between controlled and uncontrolled state.

## Why #6618 is no longer a good PR target

A fresh PR now covers this issue directly:

- PR #6620: https://github.com/superplanehq/superplane/pull/6620
- Title: `fix: keep Select controlled on empty string values`
- Status at time of investigation: open

PR #6620 already does the natural complete version of the fix:

1. Replaces `step.appId || undefined` with `step.appId`.
2. Replaces `step.entrypoint || undefined` with `step.entrypoint`.
3. Finds and fixes the same pattern in `MarkdownVariableSourceControls`.
4. States that the author swept `web_src/src` for equivalent controlled-component patterns.

Conclusion: do **not** submit a competing PR for #6618, do not add a second PR that merely adds tests for #6620, and do not broaden the global Select wrapper just to manufacture a larger change.

## Adjacent investigation: Factory Line trigger states

While reading the surrounding flow, a separate potential correctness/UX problem appeared in `FactoryLineStepEditor.tsx`.

Current query handling is effectively:

```tsx
const { data: canvas, isLoading: canvasLoading } = useCanvas(
  organizationId,
  step.appId,
  { enabled: Boolean(step.appId) },
);

const triggers = useMemo(() => listTriggerNodes(canvas), [canvas]);
```

The component ignores the query `error` state. `listTriggerNodes(undefined)` returns an empty array.

Later the UI treats an empty trigger list as:

```text
<app> has no triggers yet.
```

### Hypothesis A: canvas load errors are presented as an empty business state

Possible flow:

```text
select App
  -> canvas request starts
  -> request fails
  -> canvas is unavailable
  -> listTriggerNodes(canvas) produces []
  -> loading ends
  -> UI reports that the app has no triggers
```

This would conflate two materially different states:

- the app loaded correctly and genuinely has no triggers;
- the app could not be loaded.

The trigger Select is currently disabled only while no app is selected or while the request is loading:

```tsx
disabled={!step.appId || canvasLoading}
```

If the query fails, the Select may therefore become enabled despite having no valid trigger data.

### Existing project pattern supporting the hypothesis

`AppCanvasNodeFieldRenderer.tsx` uses the same `useCanvas` hook and explicitly distinguishes:

1. no app selected;
2. query error;
3. loading;
4. loaded but no matching nodes;
5. normal ready state.

That makes explicit error handling in `FactoryLineStepEditor` consistent with an existing SuperPlane frontend pattern rather than a new abstraction.

## Adjacent investigation: stale saved entrypoint

There is a second edge case worth reproducing before implementation.

When an existing Factory Line is loaded, its saved step is converted into draft state roughly as:

```ts
{
  name: step.name ?? "",
  appId: step.app?.app ?? "",
  entrypoint: step.app?.entrypoint ?? "",
}
```

The available triggers, however, are calculated from the **current** canvas.

Possible lifecycle:

```text
Factory Line saved:
App A -> trigger "deploy"

Later:
trigger "deploy" is removed from App A

Open Factory Line editor:
step.entrypoint === "deploy"
available triggers === ["build", "test"]
```

The editor currently has no explicit state/message for "the saved trigger no longer exists".

This may leave the form with a stored value that is not present in its selectable options. Backend validation will eventually reject an invalid/missing entrypoint, but the UI should ideally explain the problem before Save.

## Candidate PR scope

Do not implement this until the behavior is reproduced or otherwise confirmed.

If confirmed, prefer a small, local change in `FactoryLineStepEditor.tsx`. Avoid a Select refactor or new generic abstraction.

Possible shape:

```tsx
const {
  data: canvas,
  isLoading: canvasLoading,
  error: canvasError,
} = useCanvas(organizationId, step.appId, {
  enabled: Boolean(step.appId),
});

const triggers = useMemo(() => listTriggerNodes(canvas), [canvas]);

const canvasLoadFailed = Boolean(canvasError && !canvas);

const selectedTriggerMissing = Boolean(
  canvas &&
    step.entrypoint &&
    !triggers.some((trigger) => trigger.id === step.entrypoint),
);
```

Why `canvasError && !canvas` instead of just `canvasError`: if React Query has usable cached data and only a background refetch fails, the UI should not necessarily discard the existing trigger data.

Possible trigger disabling:

```tsx
disabled={!step.appId || canvasLoading || canvasLoadFailed}
```

Possible state messages:

```text
Load error:
Failed to load triggers for this app.

Stale saved entrypoint:
The selected trigger is no longer available. Choose another trigger.

Real empty state:
<App> has no triggers yet.
```

## Important non-goals

- Do not touch the `value={... || undefined}` lines in our PR if #6620 is still open or merged; that belongs to #6620.
- Do not change the global Select wrapper to coerce all `undefined` values to empty strings.
- Do not automatically clear a stale saved `entrypoint` in `useEffect`. Opening an editor should not silently mutate persisted configuration.
- Do not add a retry system, generic async-select abstraction, or broad factory-line refactor unless investigation proves it necessary.
- Do not inflate the diff for application optics. A small independently useful fix is preferable.

## Testing direction

Only add a component test if it can stay reasonably small with the repository's existing test utilities.

High-value cases, if test setup is practical:

1. canvas query error does not show "has no triggers yet";
2. trigger Select remains disabled when canvas data failed to load;
3. a saved entrypoint absent from current trigger options produces an explicit invalid/stale state;
4. a genuinely empty canvas still shows the existing "has no triggers yet" message;
5. normal loaded triggers remain unaffected.

Relevant frontend checks from SuperPlane contributor guidance:

```bash
make format.js
make check.build.ui
```

The UI-specific guide additionally recommends build/tests/lint checks when available.

## Decision gate

Proceed with this candidate only if at least one of the following is confirmed by local reproduction, Storybook/dev environment, or a reliable test:

- a failed canvas request is currently rendered as a false "no triggers" state;
- the Trigger Select becomes interactable after a failed request when it should not;
- an existing Factory Line can contain an entrypoint that no longer exists and the editor gives no actionable indication.

If these do not reproduce, abandon this path instead of forcing a PR.

## Suggested PR framing if confirmed

Possible title:

```text
fix: handle unavailable factory line triggers
```

Possible summary:

```text
While reviewing the factory line trigger selection flow, I noticed that canvas
loading failures are currently treated as an empty trigger list, which can make
the UI report that an app has no triggers when the canvas request actually
failed.

This change keeps loading, error, empty and invalid saved-trigger states distinct
without changing the underlying Factory Line draft data.
```

Do not reference #6618 as fixed by this PR. #6618 belongs to #6620.

## Current recommendation

Status: **investigate, not yet implementation-ready**.

The strongest direction is a small independent correctness fix around Factory Line trigger query/error/stale-selection states. It is adjacent to the original issue but does not duplicate PR #6620. The next step is manual/code-level reproduction before writing the patch.
