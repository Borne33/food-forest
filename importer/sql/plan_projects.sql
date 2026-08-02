-- Project Plan persistence (Aug 2026). One row per plan holds the Budget /
-- Scope / Schedule settings blob (rates, plant prices, cost categories, start
-- year, revenue toggle). Mirrors plan_layouts: RLS-scoped to the owning user,
-- cascades when the plan is deleted. The ProjectPlan component is the sole
-- writer (debounced autosave), so there is no cross-writer race.

create table if not exists public.plan_projects (
  plan_id    uuid primary key references public.plans(id) on delete cascade,
  user_id    uuid not null default auth.uid() references auth.users(id),
  data       jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.plan_projects enable row level security;

create policy plan_projects_select on public.plan_projects
  for select using (user_id = auth.uid());
create policy plan_projects_insert on public.plan_projects
  for insert with check (
    user_id = auth.uid()
    and exists (select 1 from public.plans p where p.id = plan_id and p.user_id = auth.uid())
  );
create policy plan_projects_update on public.plan_projects
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy plan_projects_delete on public.plan_projects
  for delete using (user_id = auth.uid());
