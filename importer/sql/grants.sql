-- Grant Finder persistence (Aug 2026). Catalog + per-user tracker/filters/settings.
-- Everything behind sign-in: `grants` is authenticated-read + admin-write; the
-- three per-user tables are own-row (RLS auth.uid()). The finder (grants.html)
-- reads the catalog live with the inlined window.__GRANTS__ as offline fallback.
-- Seed/update the catalog with importer/grant_import.py (source of truth:
-- importer/grants/grants_catalog.json) or the in-app admin editor.

create table if not exists public.grants (
  id text primary key, data jsonb not null, status text, deadline timestamptz,
  last_verified date, needs_verification boolean default false,
  updated_at timestamptz not null default now());
alter table public.grants enable row level security;
create policy grants_read on public.grants for select to authenticated using (true);
create policy grants_ins  on public.grants for insert to authenticated with check (auth.uid()='631158fd-3291-4f4e-9294-cff8abc5d3f8');
create policy grants_upd  on public.grants for update to authenticated using (auth.uid()='631158fd-3291-4f4e-9294-cff8abc5d3f8') with check (auth.uid()='631158fd-3291-4f4e-9294-cff8abc5d3f8');
create policy grants_del  on public.grants for delete to authenticated using (auth.uid()='631158fd-3291-4f4e-9294-cff8abc5d3f8');

create table if not exists public.grant_tracked (
  id uuid primary key default gen_random_uuid(), user_id uuid not null default auth.uid() references auth.users(id),
  grant_id text not null, data jsonb not null, updated_at timestamptz not null default now(),
  unique(user_id, grant_id));
alter table public.grant_tracked enable row level security;
create policy grant_tracked_own on public.grant_tracked for all to authenticated using (user_id=auth.uid()) with check (user_id=auth.uid());

create table if not exists public.grant_saved_filters (
  id uuid primary key default gen_random_uuid(), user_id uuid not null default auth.uid() references auth.users(id),
  name text not null, data jsonb not null, created_at timestamptz not null default now(),
  unique(user_id, name));
alter table public.grant_saved_filters enable row level security;
create policy grant_saved_filters_own on public.grant_saved_filters for all to authenticated using (user_id=auth.uid()) with check (user_id=auth.uid());

create table if not exists public.grant_settings (
  user_id uuid primary key default auth.uid() references auth.users(id),
  data jsonb not null default '{}'::jsonb, updated_at timestamptz not null default now());
alter table public.grant_settings enable row level security;
create policy grant_settings_own on public.grant_settings for all to authenticated using (user_id=auth.uid()) with check (user_id=auth.uid());
