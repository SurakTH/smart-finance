# Architecture and data rules

```mermaid
flowchart LR
  Browser[Thai Next.js UI] --> Caddy
  Caddy --> API[FastAPI]
  Caddy --> Web[Next standalone]
  API --> PG[(PostgreSQL)]
  API --> Redis[(Redis wakeups / login limits)]
  Worker --> PG
  Worker --> Redis
  Worker --> Local[Ollama / Mock]
  Worker --> Cloud[Configured Cloud adapter]
  Bot[aiogram private bot] --> PG
  Bot --> Redis
```

Only FastAPI's authenticated transaction and proposal-confirm routes can post through the ledger service. AI modules have no posting tools. AI text/JSON/images are untrusted data. Pydantic constrains extracted fields; extra output fields cannot create accounts, select financial accounts, grant permissions or trigger actions. Human confirmation supplies transaction fields and resolves workspace-local account IDs anew.

```mermaid
erDiagram
  users ||--o{ memberships : belongs
  workspaces ||--o{ memberships : has
  workspaces ||--o{ accounts : owns
  workspaces ||--o{ entries : owns
  entries ||--|{ lines : balances
  accounts ||--o{ lines : receives
  workspaces ||--o{ proposals : reviews
  proposals |o--o| entries : confirms
  attachments |o--o{ proposals : evidence
  attachments |o--o{ messages : chat_images
  workspaces ||--o{ conversations : scopes
  users ||--o{ conversations : owns
  conversations ||--o{ messages : stores
  workspaces ||--o{ providers : configures
  workspaces ||--o{ jobs : queues
  users ||--o{ sessions : authenticates
  users ||--o{ telegram_links : links
```

Workspace scoping is explicit in every query. Cross-entity tenant references have composite foreign keys on `(id, workspace_id)`. There is no implicit global workspace state on the backend. Provider API keys never leave the backend and are decrypted only immediately before the configured HTTP request.

The PostgreSQL ledger has deferred balance checks at commit, immutable entry/line triggers, and a transaction identity guard preventing line appends to an earlier journal. The application serializes financial writes using a workspace lock and commits before returning success. Journal posting must run in the outer DB transaction: the insertion guard compares the entry's xmin with the current top-level transaction ID; posting inside a database savepoint is not supported. Workers use savepoints for proposal processing only, and never post journals.

Database jobs form a durable outbox. Redis carries wakeups, not user content. Workers poll as a fallback and lock jobs with `FOR UPDATE SKIP LOCKED`, retaining the lock through bounded AI processing. Process crashes roll back the job and partial proposals; the job is available to retry after connection closure. Multiple workers can process separate jobs. Run one worker in milestone 1 to preserve chat request order; conversation-specific ordering across multiple workers is pending. After completion/failure, job payloads are cleared; normal chat messages and receipt attachments remain durable. The system does not promise exactly-once calls to external models after a worker crash, but a model call cannot post money.

Amounts are signed integer satang: debit positive, credit negative. Account balances use debit minus credit, reversing normal display for liability/income/equity. Reports derive from immutable ledger entries/lines and exclude opening/transfer/card payment from income/expense totals. Month boundaries use Asia/Bangkok and transaction dates are local calendar dates. No exchange rates or multi-currency conversion.

Threat limits: the server/database administrator is trusted; database role ownership bypasses any application restriction. No RLS, MFA, password recovery, tamper-proof external audit sink, configurable retention or formal penetration test is delivered. Login IP limits apply to the proxy peer in default Compose (forwarded IP headers are intentionally not trusted), so repeated login attempts can temporarily throttle the whole self-hosted instance. This conservative limit is appropriate to the initial single-user deployment and needs trusted-proxy configuration before larger deployment.

Source references used for implementation: [Next installation](https://nextjs.org/docs/app/getting-started/installation), [SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html), [FastAPI security](https://fastapi.tiangolo.com/tutorial/security/), [Gemini compatible API](https://ai.google.dev/gemini-api/docs/openai), [Ollama compatible API](https://docs.ollama.com/api/openai-compatibility).

## Image messages

Chat uploads use a separate authenticated multipart endpoint. Each message references an attachment through `(attachment_id, workspace_id)` and keeps its caption in conversation history. The server obtains privacy from the owned conversation, never from an upload-provided override. The extract worker validates ownership and active membership, sends only the current image/caption to the configured vision provider, then inserts pending proposals and an assistant acknowledgement in one transaction. A workspace lock serializes image deduplication before insertion. Model text has no posting capability.

Before extraction creates shared Inbox evidence, image access requires the owning conversation or the uploader's pending job. Inbox proposals and their receipt evidence are shared workspace finance data, as disclosed beside the chat composer. Deleting a conversation cancels its pending jobs and removes history; shared receipt evidence is retained. Orphan attachment retention remains pending.

Open chat rooms poll history independently of whether a pending job was observed, covering a worker that completes between the initial history request and the job refresh. Room polling cancels stale responses when the active room changes.


### Demand-driven Web Assistant reads

Configured Web Chat starts with bounded text history and workspace/date instructions, without eager account balances or management-plan snapshots. `lookup_workspace` uses server-bound tenant and room owner, strict typed resource/filter allowlists, literal name search and UUID keyset pages (10 default,20 max,3 resources/batch). Personal preferences are owner-scoped and keyword-filtered. `query_finance` uses active journals only, cursor pages of10 and366-day maximum ranges. Valid anchors must exist inside the current tenant and filters. Page state lives in the existing room context for15minutes and is included only on relevant follow-ups.

AI monthly reports use dedicated SQL totals and streamed group/budget hashing; output retains top20 rows per group plus complete group counts. No dashboard balances/daily/recent feed is computed. Full fingerprints include groups outside display limits, so stale analytical plans still fail confirmation. Read results are cached only in the job object for that turn. Provider calls/retries remain metered and bounded. Current attachments or short explicit/receipt-clarification follow-ups within15minutes may send image bytes, rather than automatically sending recent images with unrelated chat. This is bounded retrieval, not automatic long-term memory or a large-data latency guarantee.


### Owner-configured AI network destinations

Ollama supports a per-provider endpoint, falling back to the trusted server OLLAMA_URL when blank. Custom and Ollama endpoints accept HTTP(S), explicit ports, LAN, loopback, Docker names and Tailscale CGNAT destinations. This intentionally grants workspace owners access to these AI destinations from the backend network; do not treat owner configuration as an untrusted tenant URL sandbox. Custom endpoints validate syntax and every resolved address, pin DNS, retain original Host/port and HTTPS SNI, and reject link-local/metadata, unspecified, multicast and reserved destinations. Named cloud providers retain public-only resolution. All calls disable redirects and environment proxies; keys are backend-only and cleared when destination changes without a replacement key. Cloud-off still permits configured Ollama destinations, including remote machines.
