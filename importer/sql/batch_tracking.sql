-- Batch tracking: number plants by their add-time (created_at) so the app can
-- filter "what was added when". A >30-min gap between consecutive created_at
-- values starts a new batch. Historical rows are numbered by the window query;
-- future INSERTs are auto-numbered by the trigger (no manual step needed).

ALTER TABLE plants ADD COLUMN IF NOT EXISTS batch integer;

-- one-time backfill of existing rows
WITH ordered AS (
  SELECT id, created_at,
         created_at - lag(created_at) OVER (ORDER BY created_at, id) AS gap
  FROM plants
),
marked AS (
  SELECT id, created_at,
         CASE WHEN gap IS NULL OR gap > interval '30 minutes' THEN 1 ELSE 0 END AS nb
  FROM ordered
),
numbered AS (
  SELECT id, SUM(nb) OVER (ORDER BY created_at, id) AS batch FROM marked
)
UPDATE plants p SET batch = n.batch FROM numbered n WHERE p.id = n.id;

-- auto-number future inserts
CREATE OR REPLACE FUNCTION set_plant_batch() RETURNS trigger AS $$
DECLARE last_created timestamptz; last_batch int;
BEGIN
  SELECT created_at, batch INTO last_created, last_batch
    FROM plants WHERE batch IS NOT NULL ORDER BY created_at DESC, id DESC LIMIT 1;
  IF last_batch IS NULL THEN
    NEW.batch := 1;
  ELSIF coalesce(NEW.created_at, now()) - last_created > interval '30 minutes' THEN
    NEW.batch := last_batch + 1;
  ELSE
    NEW.batch := last_batch;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_set_plant_batch ON plants;
CREATE TRIGGER trg_set_plant_batch BEFORE INSERT ON plants
  FOR EACH ROW WHEN (NEW.batch IS NULL) EXECUTE FUNCTION set_plant_batch();
