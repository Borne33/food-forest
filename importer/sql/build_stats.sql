-- About-page AI footprint counter (Aug 2026). Single-row table holding the
-- maintained estimate of AI tokens used to build & maintain the site. Public
-- read (the About page shows it live); admin-only update. After each Claude
-- session that changes the site, add that session's /cost token total to this
-- figure (see HANDOFF §12). Energy/water are derived client-side from it.
create table if not exists public.build_stats (
  id int primary key default 1,
  tokens bigint not null default 0,
  updated_at timestamptz not null default now(),
  constraint build_stats_singleton check (id = 1)
);
insert into public.build_stats (id, tokens) values (1, 0) on conflict (id) do nothing;
alter table public.build_stats enable row level security;
create policy build_stats_read on public.build_stats for select using (true);
create policy build_stats_admin_update on public.build_stats for update to authenticated
  using (auth.uid() = '631158fd-3291-4f4e-9294-cff8abc5d3f8'::uuid)
  with check (auth.uid() = '631158fd-3291-4f4e-9294-cff8abc5d3f8'::uuid);
-- update pattern (run after summing /cost tokens for the session):
--   update public.build_stats set tokens = <new total>, updated_at = now() where id = 1;
