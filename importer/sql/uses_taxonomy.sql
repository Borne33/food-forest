-- Structured food/material/lifecycle taxonomy + eco vs material use split.
-- Values populated by importer/populate_uses.py (rule-based, part of backfill.py),
-- correctable on the Verify page. Drives the Database food/material/lifecycle
-- filters and the expanded-card Ecological/Material use sections.
ALTER TABLE plants
  ADD COLUMN IF NOT EXISTS food_types text[] NOT NULL DEFAULT '{}',      -- Fruit, Nut/Seed, Grain, Leafy Green, Vegetable, Root/Tuber/Bulb, Herb/Spice, Tea/Drink, Flower, Sap/Syrup
  ADD COLUMN IF NOT EXISTS material_types text[] NOT NULL DEFAULT '{}',  -- Timber/Wood, Fiber/Cordage, Basketry/Weaving, Dye, Soap/Saponin, Wax/Resin/Gum, Fuelwood, Other
  ADD COLUMN IF NOT EXISTS lifecycle text,                                -- Annual | Biennial | Short-Lived Perennial | Long-Lived Perennial
  ADD COLUMN IF NOT EXISTS eco_uses text,
  ADD COLUMN IF NOT EXISTS material_uses text;
