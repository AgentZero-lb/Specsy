-- Reversible, traceable, failure-safe match provenance.
-- Run in the Supabase SQL editor (DDL is manual — see memory: supabase-ddl-manual).
--
-- One row per decision to link a listing to a product. Nothing is ever deleted: a
-- rebuild supersedes, an unmatch reverses — both flip `status` + stamp `reversed_at`,
-- keeping full history. FKs are ON DELETE RESTRICT precisely so history can't be wiped
-- by deleting a listing/product (delete is blocked until decisions are archived).
--
--   method        'sku' | 'identity_rule' | 'llm' | 'manual'
--   source        'auto' (matcher) | 'manual' (human)
--   status        'staged' (rebuilt, not yet live) | 'active' | 'reversed' | 'superseded'
--   identity_key  the exact key that linked THIS listing (per-listing provenance)
--   evidence      jsonb: parsed attributes + link_keys (full provenance)
--   confidence    0..1
--   algo_version  ruleset version (reproducibility)
--   rebuild_run_id every decision traces to one rebuild batch
--   decided_at / reviewed_at / reviewer / reversed_at / note   lifecycle + who/why
create table if not exists match_decisions (
    id             uuid primary key default uuid_generate_v4(),
    listing_id     uuid not null references listings(id) on delete restrict,
    product_id     uuid not null references products(id) on delete restrict,
    method         text not null,
    source         text not null default 'auto',
    status         text not null default 'active',
    identity_key   text,
    evidence       jsonb not null default '{}'::jsonb,
    confidence     numeric,
    algo_version   text,
    rebuild_run_id uuid,
    decided_at     timestamptz not null default now(),
    reviewed_at    timestamptz,
    reviewer       text,
    reversed_at    timestamptz,
    note           text,
    constraint match_decisions_method_chk
        check (method in ('sku', 'identity_rule', 'llm', 'manual')),
    constraint match_decisions_source_chk
        check (source in ('auto', 'manual')),
    constraint match_decisions_status_chk
        check (status in ('staged', 'active', 'reversed', 'superseded')),
    constraint match_decisions_confidence_chk
        check (confidence is null or (confidence >= 0 and confidence <= 1))
);

create index if not exists match_decisions_active_listing_idx
    on match_decisions (listing_id) where status = 'active';
create index if not exists match_decisions_active_product_idx
    on match_decisions (product_id) where status = 'active';
create index if not exists match_decisions_staged_idx
    on match_decisions (rebuild_run_id) where status = 'staged';
create index if not exists match_decisions_status_idx on match_decisions (status);
create index if not exists match_decisions_method_idx on match_decisions (method);

-- at most ONE active decision per listing (a listing maps to a single product);
-- history rows (staged/reversed/superseded) are unconstrained.
create unique index if not exists match_decisions_one_active_per_listing
    on match_decisions (listing_id) where status = 'active';


-- ── Atomic rebuild activation ────────────────────────────────────────────────
-- Flip a fully-staged rebuild live in ONE transaction. Until this runs, production
-- mappings are untouched (listings.product_id stays on the previous products), so a
-- failure during staging leaves nothing half-applied. If anything here fails, the whole
-- function rolls back.
create or replace function activate_rebuild(p_run_id uuid) returns void
language plpgsql as $$
declare
    v_staged_count bigint;
    v_distinct_listing_count bigint;
begin
    if p_run_id is null then
        raise exception 'activate_rebuild requires a non-null run id';
    end if;

    select count(*), count(distinct listing_id)
      into v_staged_count, v_distinct_listing_count
      from match_decisions
     where rebuild_run_id = p_run_id and status = 'staged';

    if v_staged_count = 0 then
        raise exception 'activate_rebuild rejected unknown or empty run id %', p_run_id;
    end if;

    if v_staged_count <> v_distinct_listing_count then
        raise exception 'activate_rebuild rejected duplicate staged listings for run %', p_run_id;
    end if;

    -- 1. supersede the decisions that are currently live
    update match_decisions
       set status = 'superseded', reversed_at = now(),
           note = trim(both ' ' from coalesce(note, '') || ' superseded by ' || p_run_id)
     where status = 'active';

    -- 2. repoint listings to their staged products
    update listings l
       set product_id = s.product_id
      from match_decisions s
     where s.rebuild_run_id = p_run_id and s.status = 'staged' and s.listing_id = l.id;

    -- 3. un-link listings that were matched but are NOT in this rebuild (coverage drop)
    update listings
       set product_id = null
     where product_id is not null
       and id not in (select listing_id from match_decisions
                      where rebuild_run_id = p_run_id and status = 'staged');

    -- 4. activate the staged decisions
    update match_decisions
       set status = 'active'
     where rebuild_run_id = p_run_id and status = 'staged';
end $$;

-- Least privilege: a rebuild is an admin/maintenance action. activate_rebuild() must NOT be
-- reachable from the PostgREST anon/authenticated roles (it would let any client repoint the
-- whole catalogue). The function is SECURITY INVOKER (default), so even if execute leaked it
-- would run with the caller's (restricted) grants — but we revoke execute outright and grant
-- it only to service_role (the matcher's SUPABASE_SERVICE_KEY).
revoke all on function activate_rebuild(uuid) from public;
revoke all on function activate_rebuild(uuid) from anon, authenticated;
grant execute on function activate_rebuild(uuid) to service_role;
