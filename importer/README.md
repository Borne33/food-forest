# Food Forest importer

Populate the Supabase `plants` table from web sources, with you approving every
plant before it goes live. Pure Python 3 standard library — **no installs**.

## One-time setup

1. Copy the env template and fill in your secret key:
   ```bash
   cd ~/food-forest/importer
   cp .env.example .env        # .env is gitignored — never commit it
   ```
   Set `SUPABASE_SERVICE_ROLE_KEY` (Supabase Dashboard ▸ Project Settings ▸ API
   ▸ `service_role`). Leave the LLM keys blank to use the free "Route A" below.

## The workflow (Route A — free, you approve each plant)

```
 fetch  ──▶  packets/*.md  ──▶  (paste into Claude)  ──▶  drafts/*.json  ──▶  validate  ──▶  apply
```

1. **Fetch** — look up plants on GBIF (canonical name + family) and Wikipedia
   (reference text), producing a research packet per plant:
   ```bash
   python3 foodforest_import.py fetch "Beach Plum" "Prunus maritima"
   # or a batch:
   cp targets.example.txt targets.txt   # edit it
   python3 foodforest_import.py fetch --file targets.txt
   ```

2. **Draft** — open a packet from `packets/`, paste it into a Claude chat.
   Claude replies with one JSON object. Save it as `drafts/<slug>.json`
   (the packet tells you the exact filename).

3. **Validate** — check every draft against the schema and the app's controlled
   vocab (state codes, regions, evidence tiers, score ranges):
   ```bash
   python3 foodforest_import.py validate
   ```

4. **Apply** — upsert the valid drafts into Supabase. Dry-run first:
   ```bash
   python3 foodforest_import.py apply --dry-run
   python3 foodforest_import.py apply
   ```
   Upserts are keyed on `sci` (unique constraint), so re-running **updates**
   an existing plant instead of creating a duplicate.

Utility: `python3 foodforest_import.py list-remote` prints what's already in the
database.

## What is auto-filled vs. drafted

- **From authoritative APIs (deterministic):** canonical scientific name and
  `family` (GBIF); reference text (Wikipedia).
- **Derived automatically on import:** `native_regions` is computed from
  `native_states` (a region is flagged when the plant covers >=50% of that
  region's states — see `REGION` / `derive_regions` in the CLI), so you never
  hand-tune it. Get `native_states` right and regions follow.
- **Drafted with judgment, then reviewed by you:** `type`, `life`, the prose
  fields, `native_states`, `nf`/`pol`, the 7-category `scores` with evidence
  tiers, and `sources`.

Nativity is **not** stored as a score — the app computes it live from
`native_states` / `native_regions` for the user's selected state.

## Fully-automated drafting (optional)

Route A keeps you in the loop for free. If you later want hands-off drafting,
put a `GEMINI_API_KEY` (free tier) or `ANTHROPIC_API_KEY` (paid) in `.env`; the
LLM call step can then be wired to draft the JSON directly. (Not enabled by
default — quality is best when you review each plant.)

## Files

| Path                    | Purpose                                            |
|-------------------------|----------------------------------------------------|
| `foodforest_import.py`  | The CLI (fetch / validate / apply / list-remote).  |
| `.env`                  | Your secrets (gitignored).                         |
| `.env.example`          | Template.                                          |
| `targets.example.txt`   | Example batch input.                               |
| `drafts/*.json`         | Reviewed plant rows — the curated, versioned source. |
| `packets/*.md`          | Regenerable research packets (gitignored).         |
