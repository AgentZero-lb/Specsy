-- Specsy Database Schema
-- Run in Supabase SQL editor (or psql)
-- Requires: pgvector extension

create extension if not exists vector;
create extension if not exists "uuid-ossp";

-- ─────────────────────────────────────────────
-- SHOPS
-- One row per Lebanese PC shop we scrape
-- ─────────────────────────────────────────────
create table shops (
    id              uuid primary key default uuid_generate_v4(),
    slug            text unique not null,
    name            text not null,
    url             text not null,
    platform        text not null,                 -- 'woocommerce' | 'shopify' | 'custom'
    scraper_module  text not null,
    active          boolean not null default true,
    last_scraped_at timestamptz,
    created_at      timestamptz not null default now()
);

-- ─────────────────────────────────────────────
-- CATEGORIES
-- ─────────────────────────────────────────────
create table categories (
    id        serial primary key,
    slug      text unique not null,
    name      text not null,
    parent_id int references categories(id)
);

insert into categories (slug, name) values
    ('cpu',          'Processors'),
    ('gpu',          'Graphics Cards'),
    ('ram',          'Memory'),
    ('motherboard',  'Motherboards'),
    ('storage',      'Storage'),
    ('psu',          'Power Supplies'),
    ('case',         'Cases'),
    ('cooling',      'Cooling'),
    ('monitor',      'Monitors'),
    ('mouse',        'Mice'),
    ('keyboard',     'Keyboards'),
    ('headset',      'Headsets'),
    ('speaker',      'Speakers'),
    ('microphone',   'Microphones'),
    ('joystick',     'Joysticks'),
    ('drawing-pad',  'Drawing Pads'),
    ('gaming-chair', 'Gaming Chairs'),
    ('laptop',       'Laptops'),
    ('desktop',      'Desktops'),
    ('tablet',       'Tablets'),
    ('networking',   'Networking'),
    ('ups',          'UPS'),
    ('camera',       'Cameras'),
    ('projector',    'Projectors');

-- ─────────────────────────────────────────────
-- PRODUCTS
-- Canonical / normalized products.
-- One row per real-world part (e.g. "RTX 4070 Ti SUPER").
-- Embedding uses Voyage AI voyage-3 → 1024 dimensions.
-- ─────────────────────────────────────────────
create table products (
    id          uuid primary key default uuid_generate_v4(),
    category_id int not null references categories(id),
    name        text not null,
    brand       text,
    model       text,
    specs       jsonb not null default '{}',
    embedding   vector(1024),
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index products_embedding_idx
    on products using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- ─────────────────────────────────────────────
-- PRODUCT ALIASES
-- Learned mapping: raw shop name → canonical product.
-- Built up from confirmed matches; lets matching skip
-- the embedding step for names we've seen before.
-- ─────────────────────────────────────────────
create table product_aliases (
    id         uuid primary key default uuid_generate_v4(),
    product_id uuid not null references products(id) on delete cascade,
    alias      text not null unique,
    source     text not null default 'confirmed', -- 'confirmed' | 'manual'
    created_at timestamptz not null default now()
);

create index product_aliases_alias_idx on product_aliases (lower(alias));

-- ─────────────────────────────────────────────
-- EXCHANGE RATES
-- ─────────────────────────────────────────────
create table exchange_rates (
    id          serial primary key,
    date        date unique not null,
    usd_to_lbp  numeric(12, 2) not null,
    source      text not null default 'manual'
);

-- ─────────────────────────────────────────────
-- SCRAPE RUNS
-- Audit log — abort if 0 products returned.
-- ─────────────────────────────────────────────
create table scrape_runs (
    id                uuid primary key default uuid_generate_v4(),
    shop_id           uuid not null references shops(id),
    started_at        timestamptz not null default now(),
    finished_at       timestamptz,
    products_found    int,
    products_upserted int,
    status            text not null default 'running', -- 'running' | 'ok' | 'failed' | 'aborted'
    error             text
);

-- ─────────────────────────────────────────────
-- LISTINGS
-- Current price/stock per shop per product.
-- product_id is null until matching job runs.
-- ─────────────────────────────────────────────
create table listings (
    id            uuid primary key default uuid_generate_v4(),
    shop_id       uuid not null references shops(id),
    product_id    uuid references products(id),
    scrape_run_id uuid references scrape_runs(id),
    raw_name      text not null,
    sku           text,
    price_raw     numeric(14, 2),         -- null = "Request Price"
    currency      text not null,          -- 'USD' | 'LBP'
    price_usd     numeric(14, 2),
    in_stock      boolean not null default false,
    product_url   text not null,
    image_url     text,
    last_seen_at  timestamptz not null default now(),
    created_at    timestamptz not null default now(),

    unique (shop_id, product_url)
);

create index listings_product_price_idx
    on listings (product_id, price_usd asc nulls last)
    where product_id is not null;

create index listings_unmatched_idx
    on listings (created_at)
    where product_id is null;

-- ─────────────────────────────────────────────
-- PRICE SNAPSHOTS
-- One row per listing per scrape run.
-- Gives full price history for charts + price-drop alerts.
-- listings only stores the current price; history lives here.
-- ─────────────────────────────────────────────
create table price_snapshots (
    id            uuid primary key default uuid_generate_v4(),
    listing_id    uuid not null references listings(id) on delete cascade,
    scrape_run_id uuid not null references scrape_runs(id),
    price_raw     numeric(14, 2),
    currency      text not null,
    price_usd     numeric(14, 2),
    in_stock      boolean not null,
    captured_at   timestamptz not null default now()
);

create index price_snapshots_listing_time_idx
    on price_snapshots (listing_id, captured_at desc);

-- ─────────────────────────────────────────────
-- MATCH QUEUE
-- Gray-zone matches that need human confirmation
-- before a listing is linked to a canonical product.
-- Auto-confirmed when similarity_score > threshold.
-- ─────────────────────────────────────────────
create table match_queue (
    id                   uuid primary key default uuid_generate_v4(),
    listing_id           uuid not null references listings(id) on delete cascade,
    candidate_product_id uuid references products(id),
    similarity_score     float,
    status               text not null default 'pending',
    -- 'pending' | 'confirmed' | 'rejected' | 'new_product' | 'superseded'
    reviewed_at          timestamptz,
    created_at           timestamptz not null default now()
);

create index match_queue_pending_idx
    on match_queue (created_at)
    where status = 'pending';

-- ─────────────────────────────────────────────
-- BUILDS  (auth not wired yet)
-- ─────────────────────────────────────────────
create table builds (
    id          uuid primary key default uuid_generate_v4(),
    name        text not null,
    components  jsonb not null default '{}',
    total_usd   numeric(10, 2),
    created_at  timestamptz not null default now()
);
