-- Multiple named plans per user. A `plans` table (name + color) and a plan_id on
-- user_plans, so a plant can belong to several plans (once per plan). Existing
-- memberships were migrated into a default 'My Plan' per user.

CREATE TABLE IF NOT EXISTS plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
  name text NOT NULL DEFAULT 'My Plan',
  color text NOT NULL DEFAULT '#6b8f5a',
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
CREATE POLICY plans_select ON plans FOR SELECT USING (user_id = auth.uid());
CREATE POLICY plans_insert ON plans FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY plans_update ON plans FOR UPDATE USING (user_id = auth.uid());
CREATE POLICY plans_delete ON plans FOR DELETE USING (user_id = auth.uid());

ALTER TABLE user_plans ADD COLUMN plan_id uuid REFERENCES plans(id) ON DELETE CASCADE;
-- migrate: one default plan per user, assign existing rows (see DO block in history)
ALTER TABLE user_plans ALTER COLUMN plan_id SET NOT NULL;
ALTER TABLE user_plans DROP CONSTRAINT user_plans_user_id_plant_id_key;   -- was: plant once per user
ALTER TABLE user_plans ADD CONSTRAINT user_plans_plan_id_plant_id_key UNIQUE (plan_id, plant_id); -- now: once per plan
-- insert policy also requires the plan to belong to the user
CREATE POLICY "add to own plan" ON user_plans FOR INSERT
  WITH CHECK (auth.uid() = user_id AND plan_id IN (SELECT id FROM plans WHERE user_id = auth.uid()));
