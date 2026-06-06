-- As-seen structured specs per listing (BigCommerce customFields, etc.).
-- Used by the matching passes to enrich the embedding/Haiku text.
-- Shops without specs (PCandParts, Macrotronics) just store '{}'.
alter table listings add column if not exists raw_specs jsonb not null default '{}'::jsonb;
