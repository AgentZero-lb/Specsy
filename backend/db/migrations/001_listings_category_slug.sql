alter table listings add column if not exists category_slug text;
create index if not exists listings_category_slug_idx on listings (category_slug);
