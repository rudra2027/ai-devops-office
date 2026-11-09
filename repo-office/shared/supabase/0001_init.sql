-- Agent Office: database schema for all four agents.
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run.
-- Until then the services fall back to a local SQLite file, so nothing breaks; after this runs they switch to Supabase
-- automatically on next start. Every user-owned table uses row level security: a signed-in user only sees their rows.

create extension if not exists pgcrypto;

-- ---------- profiles ----------
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  display_name text,
  created_at timestamptz not null default now()
);
alter table public.profiles enable row level security;
drop policy if exists "profiles: own row" on public.profiles;
create policy "profiles: own row" on public.profiles for all using (auth.uid() = id) with check (auth.uid() = id);

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, display_name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1)))
  on conflict (id) do nothing;
  return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute function public.handle_new_user();

-- ---------- who is the admin ----------
-- Only addresses in this table can read agent data. REPLACE the placeholder below with your own admin email before running this;
-- the apps also read ADMIN_EMAILS from .env, and the two must match.
create table if not exists public.admins (email text primary key);
alter table public.admins enable row level security;  -- no policies: nobody can read or change it through the API
insert into public.admins (email) values ('you@example.com') on conflict do nothing;

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.admins
    where lower(email) = lower(coalesce(auth.jwt() ->> 'email', '')) and coalesce((auth.jwt() ->> 'email_verified')::boolean, true)
  );
$$;

-- ---------- support chat ----------
create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  agent text not null default 'support',
  title text,
  model text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'system', 'tool')),
  content text not null default '',
  ui jsonb,
  meta jsonb,
  created_at timestamptz not null default now()
);
create index if not exists messages_conv_idx on public.messages (conversation_id, created_at);
create index if not exists conversations_user_idx on public.conversations (user_id, updated_at desc);

create table if not exists public.tickets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  subject text not null,
  details text,
  priority text not null default 'normal',
  status text not null default 'open',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ---------- IaC sessions and CI/CD runs ----------
create table if not exists public.iac_sessions (
  id text primary key,
  user_id uuid default auth.uid() references auth.users(id) on delete set null,
  status text,
  data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.pipeline_runs (
  id text primary key,
  user_id uuid default auth.uid() references auth.users(id) on delete set null,
  repo text,
  ref text,
  status text,
  data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ---------- demo orders for the support bot (user_id null = visible to everyone) ----------
create table if not exists public.orders (
  id text primary key,
  user_id uuid references auth.users(id) on delete cascade,
  status text not null,
  eta text,
  items jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);
insert into public.orders (id, status, eta, items) values
  ('4412', 'processing', 'tomorrow', '["Noise-cancelling headphones"]'),
  ('5120', 'shipped', 'in 2 days', '["Standing desk", "Cable tray"]'),
  ('7788', 'delivered', 'delivered yesterday', '["USB-C hub"]'),
  ('9001', 'delayed', 'next week', '["Ergonomic chair"]')
on conflict (id) do nothing;

-- ---------- LLM performance and evaluation ----------
create table if not exists public.llm_calls (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  agent text not null,
  model text not null,
  status text not null default 'ok',
  error text,
  latency_ms int,
  input_tokens int default 0,
  output_tokens int default 0,
  cost_usd numeric(12, 6) default 0,
  trace_id text,
  meta jsonb
);
create index if not exists llm_calls_time_idx on public.llm_calls (created_at desc);
create index if not exists llm_calls_agent_idx on public.llm_calls (agent, created_at desc);
create table if not exists public.eval_runs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  run_id text,
  suite text not null,
  model text not null,
  case_id text,
  score numeric(4, 2),
  passed boolean,
  latency_ms int,
  detail jsonb
);

create table if not exists public.service_metrics (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  service text not null,
  data jsonb not null
);
create index if not exists service_metrics_time_idx on public.service_metrics (created_at desc);
create table if not exists public.dashboards (
  id text primary key,
  title text,
  spec jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ---------- row level security ----------
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.iac_sessions enable row level security;
alter table public.pipeline_runs enable row level security;
alter table public.orders enable row level security;
alter table public.tickets enable row level security;
alter table public.llm_calls enable row level security;
alter table public.eval_runs enable row level security;
alter table public.service_metrics enable row level security;
alter table public.dashboards enable row level security;

-- Customers: their own conversations, messages and tickets, nothing else. The admin can also read them to supervise.
do $$
declare t text;
begin
  foreach t in array array['conversations', 'messages', 'tickets'] loop
    execute format('drop policy if exists "%1$s: owner" on public.%1$s', t);
    execute format('create policy "%1$s: owner" on public.%1$s for all using (auth.uid() = user_id) with check (auth.uid() = user_id)', t);
    execute format('drop policy if exists "%1$s: admin read" on public.%1$s', t);
    execute format('create policy "%1$s: admin read" on public.%1$s for select using (public.is_admin())', t);
  end loop;
end $$;
drop policy if exists "tickets: admin update" on public.tickets;
create policy "tickets: admin update" on public.tickets for update using (public.is_admin()) with check (public.is_admin());

-- Infrastructure sessions and CI/CD runs: admin only.
drop policy if exists "iac_sessions: admin" on public.iac_sessions;
create policy "iac_sessions: admin" on public.iac_sessions for all using (public.is_admin()) with check (public.is_admin());
drop policy if exists "pipeline_runs: admin" on public.pipeline_runs;
create policy "pipeline_runs: admin" on public.pipeline_runs for all using (public.is_admin()) with check (public.is_admin());

drop policy if exists "orders: public demo or own" on public.orders;
create policy "orders: public demo or own" on public.orders for select using (user_id is null or user_id = auth.uid());

-- Telemetry and eval results: the services write with the publishable key, so inserts must be open;
-- reading is admin only. (Harden later by moving ingestion to a server-side secret key.)
drop policy if exists "llm_calls: insert" on public.llm_calls;
create policy "llm_calls: insert" on public.llm_calls for insert to anon, authenticated with check (true);
drop policy if exists "llm_calls: read" on public.llm_calls;
create policy "llm_calls: read" on public.llm_calls for select using (public.is_admin());
drop policy if exists "eval_runs: insert" on public.eval_runs;
create policy "eval_runs: insert" on public.eval_runs for insert to anon, authenticated with check (true);
drop policy if exists "eval_runs: read" on public.eval_runs;
create policy "eval_runs: read" on public.eval_runs for select using (public.is_admin());

drop policy if exists "service_metrics: insert" on public.service_metrics;
create policy "service_metrics: insert" on public.service_metrics for insert to anon, authenticated with check (true);
drop policy if exists "service_metrics: read" on public.service_metrics;
create policy "service_metrics: read" on public.service_metrics for select using (public.is_admin());
drop policy if exists "dashboards: admin" on public.dashboards;
create policy "dashboards: admin" on public.dashboards for all using (public.is_admin()) with check (public.is_admin());
