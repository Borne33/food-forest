-- NY protected-plant status (6 CRR-NY 193.3), Aug 2026.
-- Tags plants that appear on the state's Protected Native Plants list with their
-- category (Endangered / Threatened / Rare / Exploitably vulnerable). Surfaced
-- as a badge on the plant card and editable on the Verify page. The 151 species
-- already in the DB were tagged from the parsed 193.3 list; the ~570 missing
-- ones are added as records (see the batch import) already carrying this status.
alter table public.plants add column if not exists ny_protected_status text;
-- (data UPDATE applied from the parsed list via MCP; see nycrr193_present.csv)
