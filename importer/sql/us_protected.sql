-- US federal protected status (ESA), Aug 2026.
-- Tags plants that appear on the USFWS "species listings by tax group" report
-- (Endangered / Threatened) with their federal status. Cross-referenced by
-- genus+species against the full catalog; only 7 matched (the report is mostly
-- CA/HI/PR flowering plants, this DB is Northeast-focused). Surfaced as a card
-- badge + Database filter chip, editable on the Verify page.
alter table public.plants add column if not exists us_protected_status text;
-- data UPDATE applied from the parsed USFWS report via MCP (7 rows).
