-- Per-part harvest timing for the Harvest view (My Plans). Maps each edible
-- food_type to the month numbers (1-12) when that part is harvested, e.g.
--   {"Flower":[5,6],"Fruit":[8,9,10]}
-- Backfilled by importer/populate_harvest_calendar.py (rule-based: parses the
-- free-text `harvest` field, intersected with per-food-type typical windows).
-- Editable later on the Verify page. Non-edible plants stay {}.
alter table public.plants
  add column if not exists harvest_calendar jsonb not null default '{}'::jsonb;
