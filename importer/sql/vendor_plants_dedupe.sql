-- vendor_plants: dedupe + a unique index that actually holds (Aug 2026)
--
-- Why there were duplicates at all, despite vendor_plants_uniq already
-- existing on (vendor_id, plant_id, form, cultivar_name, size):
--
--   Postgres treats NULL as DISTINCT from NULL in a unique index. Every
--   importer sends `"form": it.get("form") or None`, so an upload whose rows
--   carry no form reaches PostgREST with form = NULL. ON CONFLICT then never
--   fires and each re-run inserts a fresh copy. Vendor 69's PDF catalogue was
--   parsed twice; 49 rows landed twice.
--
--   (The other 39 groups that collide on the 4-column key from vendors.sql are
--   NOT duplicates — they are Ernst's per-state seed ecotypes, distinguished by
--   `size` ("PA ecotype", "NY4 ecotype"). `size` belongs in the key; the live
--   index already had it and the SQL doc had drifted. vendors.sql is corrected.)
--
-- Fix, in order: normalise the NULLs away, collapse the duplicate groups,
-- forbid NULL in the key columns, then rebuild the index NULLS NOT DISTINCT so
-- a future NULL slipping through still collides instead of multiplying.

begin;

-- 1 ── keep a copy of everything this migration removes
create table if not exists public.vendor_plants_dupe_backup (like public.vendor_plants);
alter table public.vendor_plants_dupe_backup add column if not exists removed_at timestamptz default now();
alter table public.vendor_plants_dupe_backup add column if not exists kept_id bigint;

-- 2 ── drop the old index BEFORE normalising. Rewriting NULL -> '' collapses
--      rows onto each other row by row, and the unique index fires mid-statement
--      (23505) long before step 3 gets a chance to collapse them deliberately.
drop index if exists public.vendor_plants_uniq;

-- 2b ── NULL -> '' in the key columns, and trim `size` so " PA ecotype" and
--      "PA ecotype" stop being two products
update public.vendor_plants
   set form          = coalesce(form,''),
       cultivar_name = coalesce(cultivar_name,''),
       size          = coalesce(btrim(size),'')
 where form is null or cultivar_name is null or size is null or size <> btrim(size);

-- 3 ── collapse duplicates: lowest id wins
create temporary table vp_dupes on commit drop as
select id,
       first_value(id) over w                          as keep_id,
       min(first_seen)  over w                         as merged_first_seen,
       max(last_seen)   over w                         as merged_last_seen
  from public.vendor_plants
window w as (partition by vendor_id, plant_id, form, cultivar_name, size
             order by id
             rows between unbounded preceding and unbounded following);

-- the keeper inherits the widest seen-window of its group, so dropping the
-- copies never makes a listing look newer or shorter-lived than it was
update public.vendor_plants vp
   set first_seen = d.merged_first_seen,
       last_seen  = d.merged_last_seen
  from vp_dupes d
 where vp.id = d.keep_id
   and (vp.first_seen is distinct from d.merged_first_seen
     or vp.last_seen  is distinct from d.merged_last_seen);

insert into public.vendor_plants_dupe_backup
select vp.*, now(), d.keep_id
  from public.vendor_plants vp join vp_dupes d on d.id = vp.id
 where d.id <> d.keep_id;

delete from public.vendor_plants vp
 using vp_dupes d
 where vp.id = d.id and d.id <> d.keep_id;

-- 4 ── close the hole the importers kept falling through
alter table public.vendor_plants
  alter column form          set default '',
  alter column cultivar_name set default '',
  alter column size          set default '',
  alter column form          set not null,
  alter column cultivar_name set not null,
  alter column size          set not null;

-- 5 ── rebuild the key. NULLS NOT DISTINCT covers plant_id, which stays
--      nullable (an unmatched listing has no plant); a plain index would let
--      an unlimited number of NULL-plant rows pile up for one vendor.
--      Still a plain (non-partial, non-expression) index, so PostgREST can use
--      it as an ON CONFLICT target — see the 42P10 note in vendors.sql.
create unique index vendor_plants_uniq
  on public.vendor_plants (vendor_id, plant_id, form, cultivar_name, size)
  nulls not distinct;

commit;
