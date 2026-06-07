-- Hotfix for databases where migration 003 was applied before the empty-run guard.
--
-- An unknown rebuild_run_id has no staged decisions. Without this guard, the activation
-- function's "unlink listings absent from this rebuild" step would interpret that as an
-- empty catalogue and clear every product_id. Reject invalid staging before any updates.
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

    update match_decisions
       set status = 'superseded', reversed_at = now(),
           note = trim(both ' ' from coalesce(note, '') || ' superseded by ' || p_run_id)
     where status = 'active';

    update listings l
       set product_id = s.product_id
      from match_decisions s
     where s.rebuild_run_id = p_run_id and s.status = 'staged' and s.listing_id = l.id;

    update listings
       set product_id = null
     where product_id is not null
       and id not in (select listing_id from match_decisions
                      where rebuild_run_id = p_run_id and status = 'staged');

    update match_decisions
       set status = 'active'
     where rebuild_run_id = p_run_id and status = 'staged';
end $$;

revoke all on function activate_rebuild(uuid) from public;
revoke all on function activate_rebuild(uuid) from anon, authenticated;
grant execute on function activate_rebuild(uuid) to service_role;
