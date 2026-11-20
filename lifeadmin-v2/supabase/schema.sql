-- LifeAdmin Autopilot - Supabase schema. Run in: Supabase > SQL Editor
create extension if not exists "pgcrypto";

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  telegram_id bigint unique not null,
  name text,
  created_at timestamptz not null default now()
);

create table if not exists items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  name text not null,
  category text not null default 'other'
    check (category in ('electronics','appliance','vehicle','insurance','subscription','medical','other')),
  store text,
  purchase_date date,
  warranty_months int check (warranty_months between 0 and 600),
  expiry_date date,
  amount numeric(12,2) check (amount >= 0),
  currency text not null default 'INR',
  image_url text,                -- path inside the private 'bills' bucket
  confidence numeric(3,2),       -- LLM extraction confidence (1 = typed by user)
  status text not null default 'active'
    check (status in ('active','claimed','expired','archived')),
  created_at timestamptz not null default now()
);
create index if not exists items_user_idx   on items(user_id);
create index if not exists items_expiry_idx on items(expiry_date) where status = 'active';

create table if not exists reminders (
  id uuid primary key default gen_random_uuid(),
  item_id uuid not null references items(id) on delete cascade,
  stage int not null check (stage in (0,1,7,30)),   -- days-before-expiry bucket
  sent_at timestamptz not null default now(),
  unique (item_id, stage)                           -- never send the same reminder twice
);

create table if not exists claims (
  id uuid primary key default gen_random_uuid(),
  item_id uuid not null references items(id) on delete cascade,
  issue text not null,
  draft_text text not null,
  created_at timestamptz not null default now()
);

-- Only the API (service role key) touches the data; anon/public gets nothing.
alter table users     enable row level security;
alter table items     enable row level security;
alter table reminders enable row level security;
alter table claims    enable row level security;

-- Private bucket for bill photos
insert into storage.buckets (id, name, public)
values ('bills', 'bills', false)
on conflict (id) do nothing;

-- Newer Supabase projects do not give service_role access to tables created in SQL. Run this too:
grant usage on schema public to service_role;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;
