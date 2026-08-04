# SRT Coder Codebase Guide

This document describes the repository as it is implemented today. `README.md`
is the user-facing introduction; `implementation.md` is a historical build plan
whose checked and unchecked items do not always match the current code. When the
documents disagree, the Python source and the notes below are authoritative.

## 1. What the application does

SRT Coder is a local NiceGUI web application for qualitative coding of interview
transcripts. Authenticated users can:

1. upload or select an `.srt` transcript;
2. create or open an analysis attached to that transcript;
3. create structured `Differentiation`, `Comparison`, and `Nuance` coding
   objects;
4. select exact transcript ranges and assign them to schema fields;
5. enter free-text comments alongside extracted fields;
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
coded_data/*.json       mutable users, analyses, and codings

interview_data/*.srt     mutable transcript inputs
```

The intended dependency direction is UI -> domain -> storage. Most active code
follows it. The dashboard is one exception: uploaded SRT bytes are written
directly to `interview_data/`.

There are four routes:

| Route | Renderer | Purpose |
| --- | --- | --- |
| `/login` | `auth.views.render_login_page` | Username/password login |
| `/` | `ui.pages.dashboard.render_dashboard` | Transcript, analysis, import, and export navigation |
| `/analysis/{analysis_id}` | `ui.pages.analysis.render_analysis_page` | Main transcript coding workspace |
| `/agreement` | `ui.pages.agreement.render_agreement_page` | In-memory comparison of exported analyses |
| `/migration-review` | `ui.pages.migration_review.render_migration_review_page` | Read-only before/after migration audit |

Every route except `/login` is authentication-gated. The dashboard is gated in
both `app.py` and its renderer; the analysis and agreement pages gate themselves.

## 3. Runtime and startup

### `app.py`

The entry point registers the four NiceGUI routes and starts NiceGUI using the
settings from `config.py`. Before startup it ensures the export directory exists.
The `__mp_main__` guard supports NiceGUI's reload/process startup behavior.

### `config.py`

All paths are relative to the repository root:

- `interview_data/`: live SRT inputs;
- `coded_data/`: live JSON stores;
- `coded_data/exports/`: generated analysis bundles.

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

All active persisted models live in `models.py` and inherit from Pydantic
`BaseModel`. Nearly every property is optional and has an adjacent
`<property>_comment` property. This makes old or partial JSON records loadable,
but also means identity and relationship constraints are enforced by services,
not by model validation.

### Schema objects

`Comparison` contains a `comparand` and a list of `ComparatorDetail` records.
Each comparator has comparator text, adjective text, and a list of dimensions or
examples.

`Differentiation` contains top-level importance fields and a list of `Perspective`
records. Its context value/comment remain in the persisted model for lossless
compatibility, but coding and agreement views intentionally ignore them. Each
perspective captures what it is, why it matters, and its implications (including
whether it adds complexity).

`Nuance` describes an outcome/event/state, uncertainty about causality, negation,
preference stance, nested conditions, and sufficiency. Its
`condition_antecedent_reason` list holds `ConditionAntecedentReason` records for
descriptions, impact direction, reasoning, certainty, and epistemic stance.

Every extract field and its comment are plain strings. Lists are optional and are
created incrementally in the UI.

### Application records

`User` stores username, PBKDF2 password hash, role, active flag, and timestamps.

`Analysis` is a named container with a generated ID, owner username, one
interview filename, optional description, and timestamps. Analyses are visible to
all authenticated users; ownership is metadata rather than an authorization
boundary.

`CodingEntry` belongs to an analysis and transcript. It supports both older
segment/span entries and the current object-first form:

- identity and scope: `coding_id`, `analysis_id`, `interview_file`;
- type: `object_type` (`differentiation`, `comparison`, or `nuance`);
- legacy cue metadata: segment ID/index/times, speaker, quote, note;
- legacy span anchor: start/end segment and character offsets plus selected text;
- one structured payload: `comparison`, `differentiation`, or `nuance`;
- `field_spans`: mapping from a schema path to one or more exact span dictionaries;
- creator and timestamps.

A field-span key mirrors the model path, including list indexes, for example:

```text
differentiation.perspectives_extract[0].what_are_the_implications_extract
comparison.comparators[1].dimensions_or_examples[0]
nuance.condition_antecedent_reason[0].epistemic_stance_extract_comment
```

Each span dictionary contains `start_segment_id`, `start_char_offset`,
`end_segment_id`, `end_char_offset`, and `selected_text`.

### `models2.py`

This is an untracked, unused earlier schema draft. Its fields are required, it has
no comment properties, and nothing imports it. It should not be treated as part
of the active model contract.

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
- `storage/coding_repo.py` reads/writes
  `{ "schema_version": 3, "codings": [...] }`, rejects unresolved legacy data,
  requires an analysis ID for scoped listing, and looks up coding IDs.

Every save serializes and rewrites the entire collection. Repository functions do
not enforce uniqueness or relationships.

### Live and generated data

At the time of this documentation, the local stores contain six users, six
analyses, and 22 coding entries. Those counts are operational state, not fixtures
or invariants.

- `coded_data/users.json` is tracked, contains password hashes, and is sensitive.
- `coded_data/analyses.json` and `coded_data/codings.json` are gitignored mutable
  state.
- `coded_data/exports/*.json` contains generated/sample bundles and can include
  transcript extracts and user records. The directory is currently untracked.
- `interview_data/` is the live, gitignored transcript directory (72 local SRTs at
  documentation time).
- `interview_data_all/` is an untracked second corpus (67 SRTs) that active code
  never reads.
- `.nicegui/` contains per-browser session storage; `.runtime/` contains launcher
  state/logs; `.local/` contains the local `uv`; `.venv/` contains Python. These
  are runtime artifacts, not source.

Transcript and export contents may contain research participant data. This guide
documents their formats and roles, not their content.

### Startup schema migration

`domain/differentiation_migration.py` is the versioned coding-schema migration
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
expected state without writing anything.

## 8. Analysis and coding services

### `domain/analysis_service.py`

`list_analyses_for_interview` filters the full analysis store by exact filename.
`create_analysis` validates non-empty owner, filename, and name; creates a UUID4
hex ID and UTC ISO timestamps; appends the record; and rewrites the store.
`get_analysis` delegates to the repository.

The service does not verify that the owner exists or that the transcript exists.
The dashboard supplies values that normally make both true.

### `domain/coding_service.py`

All public lookup/update/delete operations require an `analysis_id`. File-aware
list helpers additionally require `interview_file`, preserving analysis and
transcript isolation.

There are two creation styles:

- `create_entry_for_segment` and `create_entry_for_span` create the older
  segment/span-oriented record. Validation checks required scope/creator fields,
  non-negative offsets, and same-segment ordering. It does not prove that IDs or
  offsets belong to the supplied transcript.
- `create_object_entry` is the active UI path. It validates the object type,
  initializes the corresponding empty schema object and empty `field_spans`, and
  appends the record.

`update_entry_payload` finds a coding only when both coding ID and analysis ID
match, selectively replaces supplied payload properties, updates the timestamp,
and rewrites all codings. A private sentinel distinguishes “leave unchanged” from
“set to null.” `update_entry_schema` is a compatibility wrapper for the older
Comparison-only editor. `delete_entry` is similarly analysis-scoped.

The service does not authorize by analysis owner, enforce that exactly one schema
payload matches `object_type`, detect duplicate spans, or coordinate concurrent
writes.

## 9. Import and export

### Export

`domain/analysis_exchange_service.export_analysis_to_file` finds one analysis,
collects all codings with its ID, then includes user records referenced by the
analysis owner or coding creators. It writes a timestamped, slugged JSON file:

```json
{
  "export_version": "2",
  "coding_schema_version": 3,
  "exported_at": "UTC ISO timestamp",
  "analyses": [],
  "codings": [],
  "users": []
}
```

The bundle includes field spans because it serializes complete coding models. It
can also include password hashes, so it must be handled as sensitive data.

### Import

The importer accepts `analyses` or the older singular `analysis` key. Version-1
and version-2 bundles are migrated sequentially in memory before validation; the
uploaded file is never modified. It then:

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

## 10. Dashboard UI

`ui/pages/dashboard.py` renders one card per live SRT and shows all analyses for
that file. Any authenticated user can open or export any listed analysis. New
analysis dialogs use the signed-in username as owner.

The SRT uploader accepts multiple files, strips directory components from upload
names, enforces the `.srt` suffix, rejects case-insensitive duplicate names, and
writes bytes directly to `interview_data/`. It does not parse or validate the
uploaded transcript before accepting it.

The JSON uploader calls the import service and displays its counts. Export calls
the export service and immediately downloads the generated file.

`ui/components/analysis_panel.py` implements an older select/create analysis
panel backed by session state. The current dashboard does not import it.

## 11. Analysis workspace UI

`ui/pages/analysis.py` is the largest active module. It owns the whole interactive
coding workspace and many nested render/event functions.

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

`domain/agreement_service.py` is UI-independent and works only on uploaded export
text. It never changes local analyses.

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

`ui/pages/agreement.py` keeps uploaded exports in a page-local Python list. Clear
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

`ui/pages/migration_review.py` lists valid timestamped backup directories and
renders a read-only three-state comparison for both migration generations:
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
authentication-gated.

## 15. Tests

The active test files cover:

- standard and JSON-in-SRT parsing, speaker extraction, timestamps, and color
  determinism (`tests/test_srt_parser.py`);
- import skipping/mapping and ID regeneration (`tests/test_analysis_exchange.py`);
- required analysis scope, file isolation, scoped schema updates, and reversed
  same-segment offset rejection (`tests/test_analysis_isolation.py`).

`tests/test_auth.py` and `tests/test_storage.py` are placeholders. Migration tests
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

The most important gaps between existing documentation and current code are:

- the agreement tool is implemented but absent from the README's project tree;
- the current object-first editor supersedes the old `coder.py`, analysis panel,
  and Comparison-only schema form;
- export already includes field spans through full model serialization;
- ordinary save operations still lack locking, while startup schema migration has
  its own lock and versioned pipeline;
- the README advertises `Stop.command`, which is absent; and
- `implementation.md` is useful history, not a reliable completion checklist.

## 17. Change guide

When changing the codebase, use these boundaries:

- schema shape or persisted record: update `models.py`, import/export behavior,
  current analysis card rendering, agreement normalization/rendering, and tests;
- transcript format: update `parsing/srt_parser.py`, parser tests, and any span
  assumptions in analysis/agreement helpers;
- storage format: update repositories, add migration/version logic, and preserve
  analysis-scoped service checks;
- coding behavior: implement rules in `domain/coding_service.py`, then invoke them
  from the UI;
- agreement definition: change `domain/agreement_service.py`; keep visualization-
  only transformations in `ui/pages/agreement.py`;
- route or authentication behavior: update `app.py` plus the page-level guard and
  add authorization tests;
- distribution: keep launchers, README instructions, dependencies, and release
  script in sync.

Before committing a behavioral change, the minimum useful verification is:

1. install/run pytest and execute the existing suite;
2. add focused tests for the changed domain/parser helper;
3. launch the app and exercise the affected route;
4. for coding changes, reload the analysis and confirm JSON persistence;
5. for span changes, check single- and multi-segment selection, deletion, and
   transcript reconstruction; and
6. for agreement changes, compare at least two known export fixtures under exact
   and partial modes.
