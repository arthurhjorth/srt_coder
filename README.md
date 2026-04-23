# SRT Coder

SRT Coder is a NiceGUI app for qualitative coding of interview transcripts (`.srt`).

It supports:
- username/password login
- coding by schema objects (`Differentiation`, `Comparison`, `Nuance`)
- text-span coding (single or multiple spans per field)
- per-field comments
- multiple analyses per transcript
- import/export of analyses as JSON bundles

## Current Behavior (Important)

- All schema fields are optional.
- All schema fields have paired `*_comment` fields in the data model.
- Non-comment fields are locked for typing in the UI and are populated by assigning highlighted spans.
- Comment fields are editable and save on blur.
- Span chips are clickable and jump to the referenced transcript location.

## High-Level Workflow

1. Log in.
2. On dashboard (`/`), pick an interview file.
3. Create a new analysis or open an existing one.
4. In analysis view (`/analysis/{analysis_id}`):
   - left side: transcript (speaker-colored cards)
   - right side: coding objects
5. Highlight transcript text and click a field add area to append a span.
6. Use span chips to jump back to source text.
7. Export an analysis from dashboard when needed.

## UI Interaction Details

### Transcript and Speaker Colors

Transcript cards are colored by speaker order in the current transcript:
- if 2 speakers: speaker 1 is light pink, speaker 2 is light green
- if 3 speakers: speaker 3 is light purple
- additional speakers use fallback palette colors

### Span Assignment

- Drag-highlight text in transcript.
- Click a field add area to append the selected span.
- Field spans are stored in `CodingEntry.field_spans[field_key]`.

### Span Display and Jump

- Each field can hold multiple spans.
- Spans are shown as separate chips.
- Clicking a chip scrolls to that exact span start in transcript.

### Clear Buttons

- Span-linked fields have `Hold 1.2s to clear`.
- Button shows countdown and red left-to-right fill while holding.
- On trigger, field value is cleared and linked spans for that field key are removed.

### Object Deletion

- Every object card has `Delete object`.
- If object is empty, delete happens immediately.
- If object has content/spans, a confirmation dialog appears with span count:
  - `Are you sure you want to delete this <object name>? It will delete everything in the <object name>, including <n> text selections/spans.`

## Data Model Overview

Primary models live in `models.py`.

- `User`
  - `username`, `password_hash`, role/active/timestamps (+ comments)
- `Analysis`
  - owner username, interview filename, name/description (+ comments)
- `CodingEntry`
  - belongs to one analysis
  - object payload: one of `differentiation`, `comparison`, `nuance`
  - optional span anchors and `field_spans`
- `Differentiation`
  - includes nested `perspectives_extract: list[Perspective]`
- `Comparison`
  - includes nested `comparators: list[ComparatorDetail]`
- `Nuance`
  - includes nested `condition_antecedent_reason: list[ConditionAntecedentReason]`

## Import / Export

Implemented in `domain/analysis_exchange_service.py` and exposed on dashboard.

### Export

- Export is per analysis.
- Output JSON includes:
  - analysis record
  - all coding entries in that analysis
  - related users referenced by owner/created_by
- Files are written under `coded_data/exports/` and downloaded via UI.

### Import Rules

Import is ID-agnostic by design.

- Source IDs are not reused.
- New local IDs are generated for analyses and codings.
- Matching and restore use names/natural keys.
- Missing users are created.
- If transcript file referenced by analysis does not exist locally, that analysis is skipped.
- Codings are imported only for analyses that were successfully mapped/imported.

### Security Note

Export bundles can contain user records and interview coding content. Handle files as sensitive data.

## Storage Layout

JSON files under `coded_data/`:
- `users.json`
- `analyses.json`
- `codings.json`
- `exports/` (generated export files)

Interview sources under `interview_data/`.

## Project Structure

```text
srt_coder/
  app.py
  config.py
  models.py

  auth/
    service.py
    views.py

  parsing/
    srt_parser.py
    speaker_color.py

  storage/
    fs_store.py
    users_repo.py
    analyses_repo.py
    coding_repo.py

  domain/
    analysis_service.py
    coding_service.py
    transcript_service.py
    analysis_exchange_service.py

  ui/
    pages/
      dashboard.py
      analysis.py
    components/
      transcript_view.py

  coded_data/
  interview_data/
  tests/
```

## Requirements

- Python 3.11+
- `nicegui`
- `pydantic`
- `pytest` (optional, for tests)

## Setup

From `srt_coder/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install nicegui pydantic pytest
```

## Run

```bash
source .venv/bin/activate
python app.py
```

Default app URL: `http://127.0.0.1:8085`

## Easy Mac Distribution (No Terminal Needed)

This repo includes double-click launchers for non-technical macOS users:

- `Start.command`
- `Stop.command`

### What `Start.command` does

On first run it automatically:
- installs a local `uv` runtime manager in `.local/`
- installs Python 3.13 (via `uv`) if needed
- creates `.venv`
- installs dependencies from `requirements.txt`
- starts the app
- opens the browser at `http://127.0.0.1:8085`

On later runs it just starts quickly and opens the app.

### What the recipient does

1. Unzip the shared folder.
2. Right-click `Start.command` and choose `Open` (first run only, due to macOS Gatekeeper).
3. Click `Open` again when prompted.
4. Use `Stop.command` to stop the app later.

### Build a shareable ZIP

```bash
./scripts/make_release_zip.sh
```

Output:
- `release/srt_coder_mac_release.zip`

## Seed User

App expects users in `coded_data/users.json`.
A local `admin` user is already present in this repository.

## Tests

```bash
source .venv/bin/activate
pytest -q
```

## Development Notes

- `app.py` is route wiring only.
- Business rules belong in `domain/`.
- JSON persistence goes through `storage/`.
- UI should call domain services, not file I/O directly.

## Known Limitations

- JSON storage is local-file based; not intended for high-concurrency production use.
- No full migration framework yet for future schema evolution.
- Export/import currently focuses on analysis portability, not user account parity across environments.
