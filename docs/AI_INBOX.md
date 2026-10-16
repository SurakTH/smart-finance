# AI Inbox

The composer keeps one image and an optional caption locally until the user submits.
It supports file selection, clipboard images and drag/drop (JPEG, PNG, WebP, 8 MB).
Text-only capture remains supported. Invalid replacements preserve the current image;
failed submission preserves the draft; switching workspaces clears the composer.

Receipt captions are sent as multipart `text` (up to 4,000 characters) together with
`file`. Inbox follows current workspace extraction routes and the workspace Cloud
permission automatically, with no per-upload mode picker. Explicit `privacy` from
legacy API clients is still honored; it cannot bypass the workspace Cloud policy. Images are sanitized server-side.
Only extract providers marked as image-capable may receive a receipt.

Extraction sends one system instruction plus the image and caption. No conversation
history, account/category list or chat tools are sent. A successful read requires one
model call; configured retries/fallback can add calls when a provider fails. Receipt
output is capped at the smaller of the configured limit and 4,096 tokens; zero uses
4,096 for receipts. Text capture and Chat retain their configured token limits.
Usage reservation uses the actual outgoing output limit. Provider-reported usage is
preferred; estimates and image token costs are not exact billing measurements.

The workspace image hash and lock prevent duplicate concurrent reads. An existing
pending job or any existing proposal reuses the previous work without another model
call. If there is no proposal and no pending job (including after failure), submitting
the same image can retry it. A different caption does not silently regenerate an
existing proposal: inspect and edit it in the review dialog. Demo fallback never
pretends to read an image's amount; it creates a clearly labelled draft with no amount.

Inbox shows only extraction job status, with old failures collapsed and dismissible
for the current visit. Drafts can be searched and filtered by attached receipt or
missing amount. Thumbnail links use workspace-authorized image endpoints. All drafts
still require the existing manual review/confirmation flow before ledger posting.
This does not verify receipt authenticity or guarantee model OCR accuracy.

Regression coverage: backend multipart caption validation, pending/success/failure
reuse, cross-workspace image isolation, image-capable routing, compact request payload,
output budget and no journal creation; browser image/caption composition, paste,
invalid replacement, filters, status isolation and existing manual confirmation.
