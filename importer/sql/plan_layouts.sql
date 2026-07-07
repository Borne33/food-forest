-- Planting Plan layout, one row per plan (the "Planting Plan" view in My Plans).
-- Stores the wizard's whole state as a JSON blob: per-plant counts (Step 1),
-- the map view + drawn polygons (Step 2), soil paint (Step 3), and plant
-- placements (Step 4). Mirrored to localStorage in-app for instant autosave;
-- this table is the cross-device source of truth. RLS scoped to the owner,
-- following the plans / user_plans pattern.
create table if not exists public.plan_layouts (
  plan_id    uuid primary key references public.plans(id) on delete cascade,
  user_id    uuid not null default auth.uid() references auth.users(id),
  data       jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.plan_layouts enable row level security;

-- read own layouts
create policy "plan_layouts_select_own" on public.plan_layouts
  for select using (user_id = auth.uid());

-- insert own layouts, and only for a plan the user owns
create policy "plan_layouts_insert_own" on public.plan_layouts
  for insert with check (
    user_id = auth.uid()
    and exists (select 1 from public.plans p where p.id = plan_id and p.user_id = auth.uid())
  );

-- update own layouts
create policy "plan_layouts_update_own" on public.plan_layouts
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());

-- delete own layouts (plan deletion also cascades)
create policy "plan_layouts_delete_own" on public.plan_layouts
  for delete using (user_id = auth.uid());
