# SRT Coder Codebase Guide

This document describes the repository as it is implemented today. `README.md`
is the user-facing introduction; `implementation.md` is a historical build plan
whose checked and unchecked items do not always match the current code. When the
documents disagree, the Python source and the notes below are authoritative.

The active application uses the simplified coding book v5. The simplified v4
and former hierarchical v3 implementations remain in the repository for
preservation and audit purposes. V4 participates only as an input to the v5
migration/import boundary; none of its pages or writable services are active.
Sections that describe older implementations call them **preserved** or
**legacy**.

## 1. What the application does

SRT Coder is a local NiceGUI web application for qualitative coding of interview
transcripts. Authenticated users can:

1. upload or select an `.srt` transcript;
2. create or open an analysis attached to that transcript;
3. create flat, simplified `Differentiation`, `Comparison`, and `Nuance` coding
   objects from coding book v5;
4. select exact transcript ranges and assign them to schema fields;
5. enter a separate comment on each coded transcript span plus dropdown comments
   and a general coder note;
6. export or import an analysis bundle; and
7. compare exported analyses in a read-only agreement workspace.

The app is deliberately local and file-backed. There is no database, API layer,
background worker, or multi-process coordination.

## 2. Architecture at a glance

```text
Browser / NiceGUI pages
        |
        +-- auth/       login and session checks
        +-- ui/         page composition and browser interactions
        |
        v
domain/                 business operations and agreement calculations
        |
        +-- parsing/    SRT decoding and speaker colors
        |
        v
storage/                Pydantic serialization and JSON repositories
        |
        v
coded_data/*.json       mutable users and analyses
coded_data/codings_simplified.json  active simplified v5 codings
coded_data/codings_v4.json          preserved v4 source

interview_data/*.srt     mutable transcript inputs
```

The intended dependency direction is UI -> domain -> storage. Most active code
follows it. The dashboard is one exception: uploaded SRT bytes are written
directly to `interview_data/`.

There are five active routes:

| Route | Renderer | Purpose |
| --- | --- | --- |
| `/login` | `auth.views.render_login_page` | Username/password login |
| `/` | `ui.pages.dashboard_v5.render_dashboard` | Transcript, analysis, v4/v5 import, and v5 export navigation |
| `/analysis/{analysis_id}` | `ui.pages.analysis_v5.render_analysis_page` | Simplified v5 transcript coding workspace |
| `/agreement` | `ui.pages.agreement_v5.render_agreement_page` | In-memory pairwise comparison of v4/v5 exports |
| `/migration-review` | `ui.pages.migration_review_v5.render_migration_review_page` | Read-only historical and v4→v5 migration review |

Every route except `/login` is authentication-gated. The dashboard is gated in
both `app.py` and its renderer; the analysis and agreement pages gate themselves.

## 3. Runtime and startup

### `app.py`

The entry point imports only the v5 dashboard, coding, agreement, and migration
review pages. Before NiceGUI starts, it runs the simplified v4→v5 schema check;
any unsafe or invalid state aborts startup. It then ensures the neutral
simplified export directory exists. The `__mp_main__` guard supports NiceGUI's
reload/process startup behavior.

### `config.py`

All paths are relative to the repository root:

- `interview_data/`: live SRT inputs;
- `coded_data/`: live JSON stores;
- `coded_data/codings.json`: preserved legacy v3 coding store;
- `coded_data/codings_v4.json`: preserved v4 source store, never overwritten by v5 migration;
- `coded_data/codings_simplified.json`: active neutral simplified store (currently book v5);
- `coded_data/exports/`: preserved legacy exports; and
- `coded_data/exports_v4/`: preserved v4 analysis bundles; and
- `coded_data/exports_simplified/`: active v5 analysis bundles.

`SRT_CODER_INTERVIEW_DATA_DIR`, `SRT_CODER_CODED_DATA_DIR`, and
`SRT_CODER_RUNTIME_DIR` can point development/test runs at isolated data. The
default paths remain inside the repository.

`SRT_CODER_HOST`, `SRT_CODER_PORT`, and `SRT_CODER_STORAGE_SECRET` override the
defaults. The default host is `127.0.0.1`, the default port is `8085`, and the
checked-in fallback storage secret is development-only.

### Dependencies

`requirements.txt` declares only `nicegui` and `pydantic`. Tests use `pytest`, but
pytest is not currently declared as a dependency.

### Launchers and packaging

- `Start.command` is the macOS launcher. It installs a repository-local `uv`,
  creates a Python 3.13 virtual environment, installs requirements, starts the
  server in the background, waits for the URL, opens the browser, records a PID,
  and logs to `.runtime/server.log`.
- `Start.bat` provides the corresponding Windows setup and foreground launch.
- `Stop.bat` force-stops processes listening on port 8085. The README and release
  script refer to `Stop.command`, but that file is not present in this checkout.
- `scripts/make_release_zip.sh` deletes and rebuilds `release/`, then packages the
  app, data, tests, and launchers. It also names the missing `Stop.command`, so the
  script cannot currently create the documented archive without that file.
- `release/srt_coder_mac_release.zip` is a generated binary release artifact.

## 4. Data model

### Shared application records

`core_models.py` contains the active `User` and `Analysis` models. Their shapes
match the preserved versions in `models.py`, so existing `users.json` and
`analyses.json` continue to load without conversion. `User` stores username,
PBKDF2 password hash, role, active flag, and timestamps. `Analysis` stores a
generated ID, owner, transcript filename, name, description, and timestamps.

### Simplified coding book v5

`coding_books/simplified_v5/models.py` is the active coding contract. Every
coding field remains optional so an object can be saved incrementally. Pydantic
forbids unknown properties and strips outer whitespace whenever a model is
validated.

Differentiation contains a focus topic and a list of `Perspective` objects. Each
perspective owns its text, selected perspective-type set, and type comment.
Comparison retains passage, A, B, relation, and optional basis.
Nuance retains relation type, X, Y, connection, expressed certainty, and
limitation. Each saved transcript span owns its optional `comment`, so two spans
assigned to the same text field can have different comments. Dropdowns retain
adjacent `*_comment` fields because they have no transcript span. All three
objects also retain the general `coder_note` without a comment on that note.
Nuance relation type accepts only problem explanation and expected effect.

Span comments are typed directly beside their coded excerpt and never require a
second transcript selection. Span comments, dropdown comments, and coder notes
are excluded from every agreement metric. Active span paths
include, for example:

```text
differentiation.thing_being_considered
differentiation.perspectives[0].text
comparison.relation
nuance.x_y_connection
```

`MigrationMetadata` retains old top-level perspective-type assignments and any
associated legacy spans so their original meaning stays auditable after types
are copied to individual perspectives.

### Preserved simplified coding book v4

`coding_books/simplified_v4/models.py` is the preserved predecessor contract. All manual
fields are optional or have empty-list defaults so an object can be saved one
field at a time. `CodingBookModel` uses `extra="forbid"` to prevent unknown
fields from being silently discarded and `str_strip_whitespace=True` to remove
leading/trailing whitespace on newly saved strings.

`DifferentiationFields` contains:

- `thing_being_considered`;
- `perspectives` (a flat string list);
- `perspective_types` (zero or more of seven enum values); and
- `coder_note`.

`ComparisonFields` contains `text_passage`, `thing_a`, `thing_b`, `relation`,
optional `comparison_basis`, and `coder_note`.

`NuanceFields` contains `relation_type`, `influence_or_action_x`,
`outcome_or_goal_y`, `x_y_connection`, conditional `expressed_certainty`,
optional `limitation`, and `coder_note`. Relation type and certainty are enums.
Certainty is hidden in the UI for ambition/intention, but a previously selected
value is retained rather than destructively cleared when the type changes.

`SimplifiedCoding` is a Pydantic discriminated union keyed by `code_type`.
`SimplifiedCodingEntry` wraps one union payload with book version 4, identity,
analysis/transcript scope, exact field spans, creator, and timestamps.

Span paths are flat and stable, for example:

```text
differentiation.thing_being_considered
differentiation.perspectives[0]
comparison.relation
nuance.x_y_connection
```

Each `TranscriptSpan` contains start/end segment IDs, character offsets, and the
canonical selected transcript text.

`coding_books/simplified_v4/labels.py` maps stable English enum/field values to
the Danish manual labels. `validation.py` returns non-blocking completeness
warnings; it does not make fields Pydantic-required.

### Preserved legacy coding models

`models.py` still contains the full hierarchical v3 models (`ComparatorDetail`,
`Perspective`, `ConditionAntecedentReason`, and the former coding entry). The
legacy services, pages, migration, and tests can still import them directly, but
the active `app.py` import graph does not. `models2.py` remains an untracked,
unused earlier schema draft.

## 5. Authentication and session state

### `auth/service.py`

Passwords use PBKDF2-HMAC-SHA256 with a random 16-byte salt and 200,000
iterations. Hashes use this format:

```text
pbkdf2_sha256$iterations$salt_hex$digest_hex
```

Verification rejects malformed or unknown formats and uses constant-time digest
comparison. Authentication trims the username, rejects unknown/inactive users,
and verifies the stored hash.

Successful login stores only `username` in NiceGUI's per-user storage.
`require_auth_or_redirect` redirects anonymous clients to `/login`. There is no
role check, owner check, account management UI, password change flow, expiry, or
server-side revocation mechanism.

### `auth/views.py`

`render_login_page` redirects an already signed-in client to the dashboard and
otherwise renders the credential form. `top_nav` displays the current username
and logout action.

### `state/session_state.py`

This thin wrapper stores `selected_interview_file` and `selected_analysis_id` in
NiceGUI user storage. The active analysis page updates both. These values are UI
conveniences; services still require explicit IDs and filenames.

## 6. Transcript parsing

### `parsing/srt_parser.py`

`TranscriptSegment` is an in-memory dataclass containing stable display ID,
numeric cue index, millisecond bounds, speaker, and text.

The normal parser:

1. splits cues on blank lines;
2. accepts an optional numeric cue number;
3. requires `HH:MM:SS,mmm --> HH:MM:SS,mmm`;
4. joins the remaining lines as cue text;
5. recognizes a leading `[Speaker name]`; and
6. assigns IDs such as `seg-00001`.

Malformed blocks are silently skipped. Empty/unlabelled speakers become
`Unknown`. A guard prevents JSON beginning with `[{...` from being mistaken for
a speaker tag.

Some source recordings contain one SRT cue whose text is a JSON array of objects
with `Start`, `End`, `Speaker`, and `Content`. If normal parsing produces exactly
one cue, `_try_parse_json_payload` converts that array into segments. Its tolerant
decoder returns all complete leading objects even when the JSON array is
truncated.

### `parsing/speaker_color.py`

With transcript speaker order available, the first speakers receive pink, green,
and purple in that order, followed by a repeating palette. Without order, a
SHA-256 hash of the normalized speaker name selects a deterministic palette
color.

### `domain/transcript_service.py`

The service lists `.srt` files in `interview_data/`, case-insensitively sorts
their names, and only loads a filename present in that listing. That membership
check prevents path traversal. Files are read as UTF-8 with a UTF-8-BOM fallback.
The returned `TranscriptDocument` includes parsed segments and speakers in first
appearance order.

## 7. Persistence

### `storage/fs_store.py`

`read_json` returns a caller-provided default when a file is absent and otherwise
uses the standard JSON decoder. `write_json` writes indented UTF-8 JSON to a
temporary file in the destination directory and atomically replaces the target.
This protects against partially written files, but there is no file lock. Two
simultaneous read-modify-write operations can overwrite one another.

Malformed JSON, permission failures, and Pydantic validation errors propagate to
the caller.

### Repository modules

- `storage/users_repo.py` reads/writes `{ "users": [...] }` and finds exact,
  case-sensitive usernames.
- `storage/analyses_repo.py` reads/writes `{ "analyses": [...] }` and looks up by
  analysis ID.
- `storage/simplified_coding_repo.py` is active and reads/writes an envelope with
  `storage_format_version: 1`, `coding_book_version: 4`, and `codings`. It rejects
  a wrong format/book version, validates every `SimplifiedCodingEntry`, and
  rejects duplicate coding IDs.
- `storage/coding_repo.py` is the preserved legacy v3 repository. It reads/writes
  `{ "schema_version": 3, "codings": [...] }` but is not imported by the active
  app.

Every save serializes and rewrites the entire collection. Repository functions do
not enforce uniqueness or relationships.

### Live and generated data

At the time of this documentation, the local stores contain six users, six
analyses, and 22 coding entries. Those counts are operational state, not fixtures
or invariants.

- `coded_data/users.json` is tracked, contains password hashes, and is sensitive.
- `coded_data/analyses.json`, preserved `coded_data/codings.json`, preserved
  `coded_data/codings_v4.json`, and active `coded_data/codings_simplified.json`
  are mutable state. The v5 repository opens only the neutral store.
- `coded_data/exports/*.json` contains generated/sample bundles and can include
  transcript extracts and user records. The directory is currently untracked.
- `coded_data/exports_v4/*.json` contains preserved v4 bundles;
  `coded_data/exports_simplified/*.json` contains active v5 bundles.
- `interview_data/` is the live, gitignored transcript directory (72 local SRTs at
  documentation time).
- `interview_data_all/` is an untracked second corpus (67 SRTs) that active code
  never reads.
- `.nicegui/` contains per-browser session storage; `.runtime/` contains launcher
  state/logs; `.local/` contains the local `uv`; `.venv/` contains Python. These
  are runtime artifacts, not source.

Transcript and export contents may contain research participant data. This guide
documents their formats and roles, not their content.

### Active simplified v4→v5 migration

`domain/simplified_schema_migration.py` runs before the server. If a valid v5
neutral store exists, it validates it and makes no change. If the neutral store
is absent and `codings_v4.json` exists, it takes an exclusive migration lock and
copies the exact original `analyses.json` and `codings_v4.json` into a timestamped
folder under `coded_data/old_schema_analyses/`. Both copies must parse as JSON
and match the live SHA-256 checksums before transformation starts.

The pure transformation turns perspective strings into objects, copies each old
top-level type to every perspective, creates a typed empty placeholder when
necessary, rekeys perspective span paths, and stores unexpected type span paths
in audit metadata. Each ambition/intention object becomes an expected-effect
object without changing its ID, position, content, certainty, limitation, note,
spans, or timestamps. New per-span and dropdown comments initialize to null.

The complete result is validated and tested for idempotence in memory and in a
temporary file. Only then is `codings_simplified.json` atomically created. The v4
source and `analyses.json` are never overwritten. Failed post-publication checks
remove the new neutral file; all other failures leave live files untouched and
abort startup. The manifest records checksums, counts, affected IDs, span moves,
type copies, and ambition recodes.

### Preserved legacy v1→v3 startup schema migration

`domain/differentiation_migration.py` is the preserved versioned coding-schema migration
pipeline. It inspects the declared version and raw coding JSON before Pydantic
validation. Unversioned/version-1 data runs v1→v2→v3, version-2 data runs v2→v3,
and raw legacy-key detection repairs inconsistent declarations. Before running
the selected steps it acquires a startup lock and creates a timestamped backup under
`coded_data/old_schema_analyses/`. The backup contains byte-identical
`analyses.json` and `codings.json` files plus a manifest with SHA-256 hashes,
record counts, source/target versions, applied steps, and affected coding IDs.

Only after backup verification does the pipeline run every required step in
memory. v1→v2 merges the retired Differentiation fields. v2→v3 merges Nuance
certitude/epistemic modality and top-level epistemic stance into uncertainty about
causality, then appends a populated parent condition as a nested condition
description. Values, comments, and span objects move together without reindexing
existing nested conditions. The pipeline validates the complete schema-version-3
result and atomically replaces `codings.json` once. Failed post-write validation
restores the verified original; any migration failure aborts server startup and
writes a copyable diagnostic to `.runtime/migration_error.txt`.

Manifests also record per-step populated value/comment counts, legacy span
path/span counts, created nested conditions, completion time, and the
post-migration coding-store checksum. `domain/migration_review_service.py` uses
the immutable backup and pure migration functions to reconstruct the current
expected state without writing anything. Neither legacy module is imported or
executed by the active v5 application. The files and all existing backups remain
intact and appear as read-only summaries on the v5 migration-review page.

## 8. Analysis and coding services

### `domain/analysis_service.py`

`list_analyses_for_interview` filters the full analysis store by exact filename.
`create_analysis` validates non-empty owner, filename, and name; creates a UUID4
hex ID and UTC ISO timestamps; appends the record; and rewrites the store.
`get_analysis` delegates to the repository.

The service does not verify that the owner exists or that the transcript exists.
The dashboard supplies values that normally make both true.

### `domain/simplified_coding_service_v5.py`

This is the active v5 service. All list, update, and delete operations require an
analysis ID; file-aware listing also requires the transcript filename. Object
creation accepts only the three book-v5 types and initializes the corresponding
empty discriminated payload. Updates validate the payload against the existing
object's concrete type, prevent changing the type after creation, validate all
spans, update the timestamp, and save through the neutral v5 repository.
Perspective removal deletes all paths belonging to the removed row and shifts
later perspective indexes down without touching unrelated paths.

`domain/coding_service.py` remains the legacy hierarchical service and is not
imported by `app.py` or any active v5 page. The v4 simplified service is likewise
preserved but inactive.

## 9. Import and export

### Export

`domain/simplified_analysis_exchange_service_v5.export_analysis_to_file` finds
one analysis, collects only v5 codings with its ID, and includes referenced
users. It writes a timestamped, slugged JSON file under
`coded_data/exports_simplified/`:

```json
{
  "export_format_version": 1,
  "coding_book_version": 5,
  "exported_at": "UTC ISO timestamp",
  "analyses": [],
  "codings": [],
  "users": []
}
```

The bundle includes field spans and may include password hashes, so it must be
handled as sensitive data. Legacy v1-v3 data is never included.

### Import

The v5 importer accepts exact v5 bundles and converts simplified v4 bundles in
memory. It never changes the uploaded file and rejects hierarchical v3, malformed,
or future bundles before reading any local store. It then:

1. adds missing users by case-insensitive username;
2. skips analyses whose transcript filename is not locally available;
3. creates inactive `role="imported"` placeholder users for missing owners or
   creators;
4. skips an analysis whose case-insensitive natural key `(owner, transcript,
   name)` already exists;
5. generates new IDs for imported analyses and codings; and
6. imports only codings whose source analysis received a new ID mapping.

Consequently, codings belonging to a skipped existing analysis are skipped rather
than merged into that existing analysis. The three stores are saved sequentially,
without a transaction; a later save failure can leave a partial import.

`domain/analysis_exchange_service.py` and the v4 simplified exchange service are
preserved and are not imported by the active app.

## 10. Dashboard UI

`ui/pages/dashboard_v5.py` renders one card per live SRT and shows all analyses for
that file. Any authenticated user can open or export any listed analysis. New
analysis dialogs use the signed-in username as owner. The page identifies coding
book v5, exports v5 codings, accepts v4/v5 imports, and links to the v5 agreement
and migration-review routes.

The SRT uploader accepts multiple files, strips directory components from upload
names, enforces the `.srt` suffix, rejects case-insensitive duplicate names, and
writes bytes directly to `interview_data/`. It does not parse or validate the
uploaded transcript before accepting it.

The JSON uploader calls the import service and displays its counts. Export calls
the export service and immediately downloads the generated file.

`ui/components/analysis_panel.py` implements an older select/create analysis
panel backed by session state. The current dashboard does not import it.

## 11. Analysis workspace UI

### Active v5 workspace

`ui/pages/analysis_v5.py` owns the active interactive coding workspace. It reads
and writes only v5 `SimplifiedCodingEntry` records through the v5 service. The left
third shows the transcript; the right two thirds show flat coding cards and the
three create buttons.

Differentiation starts with two visible perspective subcards without making the
Pydantic list required. Each saved perspective owns its text and types and can be
removed with safe span reindexing. Comparison and Nuance show their flat manual
fields, per-span comments, dropdown comments, and coder note.
Ambition/intention is absent.

Transcript-derived text fields are locked to span selection. The page captures a
DOM selection on mouse-down, normalizes it against the transcript, appends the
canonical selected text and exact offsets, clears the browser selection cache,
then persists and re-renders only the affected object. Span deletion rebuilds a
primary field from the remaining span texts. Every saved span renders its own
typed comment box directly below the excerpt; it does not require or accept a
second transcript selection. Coder notes save on blur and receive no transcript
span. Scalar/comment saves do not rerender the card, so a pending delete click is
not destroyed by a blur handler.

Each parent object is an expansion panel. Open/closed state survives local card
rerenders and the page includes collapse-all and expand-all actions. The delete
button lives in the panel header and stops expansion event propagation; one click
opens confirmation even when a comment currently has focus. Confirmed deletion
reloads storage, the visible count, cards, and transcript highlights.

Completeness warnings come from the coding-book validation module. They are UI
guidance only and never block incremental saves. Leading/trailing whitespace is
also stripped by Pydantic when the resulting model is validated.

### Preserved legacy workspace

`ui/pages/analysis.py` is the former hierarchical workspace. It remains intact
for source and audit continuity but is not imported by the active app. The
remaining details in this subsection describe that legacy implementation.

### Page state and layout

The page loads the analysis and its transcript, stores the selected analysis/file
in session state, and renders:

- transcript cards in a scrollable left third;
- create-object buttons and coding cards in the right two thirds;
- object count/status, compact mode, and collapse/expand-all controls.

Entries are filtered by both analysis ID and transcript filename and sorted by
creation timestamp. Unknown or legacy object types fall back to the Comparison
card; the legacy type `consider` is treated as Differentiation.

### Selection capture and field assignment

An injected browser script listens for selection changes and stores the most
recent non-collapsed selection in `window.__srt_last_selection`. It finds the
surrounding `.segment-text` elements, converts DOM range offsets to offsets within
each transcript segment, normalizes selection direction, and increments a
revision counter on mouse/touch/key completion.

A 200 ms NiceGUI timer polls that state to display the current selection as a
blue pending highlight. Clicking a field's dashed add area on mouse-down reads
the cached selection before focus destroys it. `parsing/span_normalization.py`
clamps it against the loaded transcript, moves its anchors past outer Unicode
whitespace, rejects whitespace-only selections, and reconstructs selected text
from transcript segments. The UI then appends that canonical text to the schema
value separated by a newline, appends the adjusted anchor dictionary under the
field path, persists the whole entry, and clears the cached selection.

This normalization applies only to newly created spans. Existing stored anchors
are deliberately not rewritten or migrated; interior whitespace remains exactly
as it appears in the transcript.

Saved spans appear as clickable chips. Clicking scrolls the transcript to the
start segment and briefly outlines it. Deleting a span rebuilds a non-comment
field's text by joining its remaining `selected_text` values. Comment text is not
rebuilt when a comment span is removed because comments are independently
editable.

### Object editors

Each object is an expansion card:

- Differentiation renders four top-level extract/comment pairs and a mutable list
  of three-field Perspective editors. New objects start with two empty
  perspectives; this minimum is UI guidance and does not alter older analyses.
- Nuance renders seven top-level extract/comment pairs and a mutable list of
  five-field Condition/Antecedent/Reason editors.
- Comparison renders the comparand pair, a mutable comparator list, comparator
  and adjective pairs, a mutable dimension/example string list, and one comment
  for that list.

Extract fields are locked display areas populated by spans. Comment fields are
textareas saved on blur and can also receive selected transcript text. Clear
buttons require a 1.2-second press, null the field, and remove that field's span
list.

Removing a nested perspective, condition, comparator, or dimension updates the
model list but does not re-key or remove affected `field_spans`. Because paths
contain indexes, spans may become orphaned or point at the wrong list item after
such a removal. This is an important current maintenance limitation.

Object deletion is immediate when the payload, note, and spans are empty;
otherwise it asks for confirmation and reports the total span count.

### Transcript highlighting

`_build_highlight_ranges` expands legacy entry anchors, all field spans, and
legacy full-segment markers into per-segment character ranges. Multi-segment
spans include the tail of the first cue, every middle cue, and the head of the
last cue. Bad/missing segment IDs are ignored and offsets are clamped.

`ui/components/transcript_view.py` renders speaker-colored cards, timestamps,
speaker badges, coded/selected rings, and escaped text. It creates a per-character
mark array, merges overlapping saved ranges, and lets pending selection styling
override saved styling.

### Older UI components

`ui/components/schema_form.py` is an unused earlier Comparison-only editor with a
manual save button and comma-separated dimensions. `ui/components/analysis_panel.py`
is the unused earlier dashboard panel. `ui/pages/coder.py` and
`ui/components/notifications.py` contain only placeholders. All package
`__init__.py` files are empty or comments only.

## 12. Agreement domain

### Active v5 agreement service

`domain/simplified_agreement_service_v5.py` is UI-independent and accepts v5
exports plus in-memory-migrated v4 exports. Every agreement-eligible `field_spans` item
becomes a normalized annotation; all `*_comment` paths and coder notes are
excluded before matching. Match rules support exact/partial span overlap,
exact/normalized/ignored field paths, and optional same-code-type enforcement.

Each source pair uses deterministic maximum-cardinality one-to-one span matching,
then total overlap quality and stable ordering as tie-breakers. It reports
TP/FP/FN, precision, recall, and F1. Coding objects of the same parent type are
aligned by any overlapping coded span; the alignment then records separately
whether their designated primary fields overlap. Relation type, expressed
certainty, and per-perspective
type sets receive a separate categorical agreement score only inside aligned
objects/perspectives; pairs where both values are missing are excluded. JSON and
UTF-8 CSV serializers expose rules, source metadata, alignment, metrics, and
discrepancies.

### Preserved legacy agreement service

`domain/agreement_service.py` is the former hierarchical agreement engine. It is
not imported by the active app. The remaining details in this section document
that preserved implementation.

### Normalization

`load_agreement_export` validates analyses/codings, chooses a display label from
analysis owner then coding creator then filename, and turns every valid
`field_spans[field_path]` item into a `NormalizedAnnotation`. Invalid/missing span
data becomes a warning. Entries without field spans contribute no annotations.

Annotation metadata includes source, analysis, transcript, coding/object IDs,
the exact field path, a normalized path with numeric list indexes changed to
`[]`, a root object key, optional embedded list-parent path, and the parsed span.

### Matching rules

`AgreementRules` controls:

- span mode: partial overlap or exact;
- field mode: exact path, normalized path, or ignored; and
- whether object types must match.

Different sources never self-match, and non-empty differing transcript filenames
never match. Partial spans match on half-open overlap. The domain's exact-span
comparison compares the frozen `TranscriptSpan` dataclass, which includes
`selected_text`; therefore equal coordinates with different selected text do not
match in this mode.

Normalized field matching ignores list indexes but retains the rest of the path.
It does not require root or embedded object identity; graph diagnostics report
the structural consequences separately.

### Clusters and pair metrics

Matching annotations are unioned into connected components. This is transitive:
if A overlaps B and B overlaps C, all three can share a cluster even when A and C
do not directly match. A full-agreement cluster contains at least one annotation
from every uploaded source.

For every source pair the service calculates:

- cluster overlap/union and Jaccard-like cluster score;
- greedy one-to-one annotation matches, sorted by overlap quality;
- TP, FP, FN, precision, recall, and F1; and
- root/embedded split and merge diagnostics based on which coding objects the
  matched annotations connect.

The overlap quality calculation is exact within one segment. Cross-segment
distance is intentionally coarse, so partial-match ranking for multi-segment
spans should not be interpreted as a precise character-level ratio.

## 13. Agreement UI

`ui/pages/agreement_v5.py` reserves a source index before each asynchronous file
read, preserving selection order. It hashes uploads to reject duplicate content
and shows per-file errors, Remove, and Clear controls. More than two uploads
produce all pairwise summaries and a selectable detailed pair.

For the selected source pair, an object-level table reports how many
Differentiation, Comparison, and Nuance objects each coder identified. It splits
one-to-one object overlaps into primary-field overlaps and partial-only overlaps,
and reports each coder's remaining no-overlap count. Object pairing uses any
overlapping coded span; primary fields are the Differentiation focus topic,
Comparison Thing A/Thing B, and Nuance outcome Y.

Above the table, every uploaded filename receives a stable display letter in
current source order (`A`, `B`, `C`, and so on), and the selected pair is stated
explicitly. Table columns and detail cards reuse those letters.

The detailed view combines aligned and no-overlap objects in one stream. It can
group first by parent code and then transcript position, or interleave all three
codes strictly by transcript position. Aligned objects appear side by side;
unmatched objects use the same full card renderer in a single-coder card. Field
colors use the concrete source, coding ID, path, and actual matched annotation;
categorical dropdowns use their separate categorical result. Comments and coder
notes are always neutral. Focused transcript evidence uses the local SRT where
available and exported text/coordinates otherwise. The old Mermaid, Sankey, and
graph-heavy views remain only in preserved pages.

`ui/pages/agreement.py` is the preserved legacy visualization and is not imported
by the active app. It keeps uploaded exports in a page-local Python list. Clear
or page reload discards them. Controls choose match rules, full transcript rows,
and compact/full Mermaid text.

It renders:

1. summary counts;
2. read-only schema trees with agreed fields in green;
3. a two-source field-type confusion matrix based on span-only greedy matching;
4. per-analysis Mermaid object graphs;
5. a cross-source agreement graph and pairwise root/embedded Sankey mappings;
6. a transcript-aligned grid of shared and unique annotations;
7. pairwise metrics and graph warnings; and
8. up to 250 agreement-cluster table rows.

The confusion matrix deliberately ignores field and object-type matching to show
which field types coders assigned to the same span. Its exact mode compares span
coordinates only, unlike the domain exact matcher noted above.

The transcript grid tries to load each referenced local transcript. Missing files
are reported and span metadata still renders. Shared multi-segment annotations
are shown in full at a primary segment and as continuation chips in other covered
segments. Mermaid labels are escaped/wrapped and diagram dimensions scale with
node/link count subject to large caps.

## 14. Migration review UI

`ui/pages/migration_review_v5.py` and
`domain/simplified_migration_review_service_v5.py` list both the new simplified
v4→v5 backups and historical v1–v3 manifests. For v4→v5 they render a read-only
three-state comparison:
retained content before migration, content moved from retiring fields, and the
deterministic expected result. It also compares expected values and span ordering
with the current live coding by ID.

Blue panels represent retained data, amber panels represent migrated legacy data,
green panels represent the expected result, and red panels flag current values
that differ. The page uses schema versions and the manifest's post-migration
checksum to distinguish an unchanged migrated store, a later schema upgrade, and
later edits. For older or transitional manifests without an explicit step list,
the review infers the step from the backed-up schema and raw retiring keys without
modifying the manifest. It never modifies backup or live data and is
authentication-gated. Historical hierarchical manifests remain readable as
summaries without reactivating their coding interface.

## 15. Tests

The active v5 test files cover:

- optional fields, nested perspective types, per-span/dropdown comments, whitespace, and
  ambition/intention rejection (`tests/test_simplified_v5_models.py`);
- strict neutral-store CRUD, object and perspective deletion, and span reindexing
  (`tests/test_simplified_v5_storage.py`);
- v4→v5 transformation, exact backups, checksums, lock contention, idempotence,
  failure cleanup, future/inconsistent versions, and manifests
  (`tests/test_simplified_v5_migration.py`);
- in-memory v4 imports and v5 exports (`tests/test_simplified_v5_exchange.py`);
- maximum-cardinality matching, parent-code summaries, primary/partial/no-overlap
  classification, transcript-ordered review items, object-specific status keys,
  categorical agreement, comment exclusion, and downloads
  (`tests/test_simplified_v5_agreement.py`); and
- migration-review reconstruction and later-edit detection
  (`tests/test_simplified_v5_migration_review.py`).

The preserved v4 test files still cover:

- optional flat Pydantic fields, enum validation, whitespace normalization, and
  non-blocking completion guidance (`tests/test_simplified_v4_models.py`);
- strict separation of the v4 and legacy stores, version rejection, CRUD, and
  preservation of legacy bytes (`tests/test_simplified_v4_storage.py`);
- v4 export/import round trips, rejection of old coding books before local data
  changes, and exact/partial agreement (`tests/test_simplified_v4_exchange_and_agreement.py`);
  and
- the fresh-process active import graph and distinct storage paths
  (`tests/test_active_v4_wiring.py`).

The retained legacy test files cover:

- standard and JSON-in-SRT parsing, speaker extraction, timestamps, and color
  determinism (`tests/test_srt_parser.py`);
- import skipping/mapping and ID regeneration (`tests/test_analysis_exchange.py`);
- required analysis scope, file isolation, scoped schema updates, and reversed
  same-segment offset rejection (`tests/test_analysis_isolation.py`).

`tests/test_auth.py` and `tests/test_storage.py` are placeholders. Legacy migration tests
cover field/comment/span merging, purity, idempotence, exact backups, rollback,
mixed-version detection, legacy imports, and failure messages. There are no tests
for most agreement UI rendering, password hashing, concurrent ordinary writes,
nested-list span reindexing, route authorization, or full end-to-end behavior.

Migration-review service tests cover v1 and v2 before/expected/current
reconstruction, checksum-based later-edit detection, historical-schema detection,
backup discovery, and read-only behavior.

Tests monkeypatch module globals manually rather than using pytest fixtures or
`monkeypatch`; restoration happens in `finally` blocks.

## 16. Repository status and source-of-truth notes

The working tree was already dirty when this guide was written. In particular,
`README.md` is modified, and `implementation.md`, `models2.py`, `Stop.bat`,
`interview_data_all/`, and the export directory are untracked. This guide does not
assume those artifacts should be committed or deleted.

The most important source-of-truth notes are:

- `core_models.py` and `coding_books/simplified_v5/models.py` define the active
  contracts; v4 and `models.py` define preserved coding books;
- the active app never reads or writes `coded_data/codings.json`, runs no legacy
  v1→v3 migration, and exposes a read-only v5 migration-review route;
- old coded data, old migration code, and old UI modules remain present for
  retention and audit purposes but are not wired into the v5 application;
- v5 export writes only book 5; import and agreement accept v5 and convert
  simplified v4 in memory, while hierarchical v3 and future books are rejected;
- ordinary save operations still lack locking;
- the README advertises `Stop.command`, which is absent; and
- `implementation.md` is useful history, not a reliable completion checklist.

## 17. Change guide

When changing the active codebase, use these boundaries:

- shared user/analysis shape: update `core_models.py` and all active repositories
  and services that consume it;
- v5 coding shape or persisted record: update
  `coding_books/simplified_v5/models.py`, its labels/completion guidance, v5
  import/export behavior, current analysis-card rendering, agreement
  normalization/rendering, and tests;
- transcript format: update `parsing/srt_parser.py`, parser tests, and any span
  assumptions in analysis/agreement helpers;
- neutral v5 storage format: update `storage/simplified_coding_repo_v5.py` and its
  strict envelope checks; do not overwrite either older store;
- active coding behavior: implement rules in
  `domain/simplified_coding_service_v5.py`, then invoke them from
  `ui/pages/analysis_v5.py`;
- active agreement definition: change `domain/simplified_agreement_service_v5.py`;
  keep rendering-only transformations in `ui/pages/agreement_v5.py`;
- route or authentication behavior: update `app.py` plus the page-level guard and
  add authorization tests;
- distribution: keep launchers, README instructions, dependencies, and release
  script in sync.

Before committing a behavioral change, the minimum useful verification is:

1. install/run pytest and execute the existing suite;
2. add focused tests for the changed domain/parser helper;
3. launch the app with isolated data paths and exercise the affected route;
4. for coding changes, reload the analysis and confirm JSON persistence;
5. for span changes, check single- and multi-segment selection, deletion, and
   transcript reconstruction; and
6. for agreement changes, compare at least two known export fixtures under exact
   and partial modes.
