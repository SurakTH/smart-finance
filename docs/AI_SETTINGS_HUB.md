# AI settings hub — stage 1

The owner settings page now has five panels, with Models selected by default:
Models/routes, Connections, Usage/budget, My memory and AI Lab. Models has a
separate Chat/text-receipt task selector. The active panel is encoded as the
`section` query parameter, supports browser back/forward and keyboard arrows,
and resets in the usual workspace-keyed component lifecycle. On mobile the five
panel tabs scroll horizontally without widening the document.

Panels load their data on first visit. Previously visited forms stay mounted and
hidden, so switching panels does not discard unsaved memory or budget edits.
Personal memory reads only preferences/accounts, while the usage panel reads
workspace usage/providers. Members retain access to their own memory and never
receive owner configuration, usage or lab controls through this page.

Model cards display the current routing role (primary/backup, disabled or blocked
by workspace Cloud policy), selected output/Thinking/Temperature and image ability.
Timeout/retry details are collapsed; secondary discovery, duplicate and delete
operations live in the more menu. Duplicating copies settings, never an API key.
The separate Connections view exposes configured destinations and whether an
encrypted key exists, never the key itself.

Tests are explicit user actions: Test or Save and test. Saving does not otherwise
invoke a provider. Save and test persists the settings first; a failed probe does
not roll back or hide a successful settings save. Probe results carry the time in
Asia/Bangkok and are labelled as results for the current page session. Reloading
starts with no in-session probe result; no persisted health claim is fabricated.
Visiting models, memory, usage or lab never automatically starts an AI generation.

## Deliberately separate second stage

The existing database Provider record still owns one model/task, URL and encrypted
key. This stage does not merge credentials or claim connections are already shared.
A later schema migration can introduce a reusable Connection and model/task profiles,
then allow one connection across models/tasks without repeating keys. It needs an
explicit migration/compatibility design to preserve existing priorities, task-specific
parameters, keys, provider IDs used by usage/pricing and workspace isolation.
Persisting probe history and invalidating old results on configuration changes can
be addressed with that migration; current probe status is explicitly session-only.

Validation includes the existing settings/model tuning, owner/member personalization
and lab regressions, plus panel boundaries, retained drafts, reload navigation,
current routing status, no implicit AI calls and save-and-test success/failure.
