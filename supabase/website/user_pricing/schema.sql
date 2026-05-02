-- ============================================================================
-- user_pricing — billing & payments schema
-- ============================================================================
-- Tables created here back the PricingRepository in
-- website/features/user_pricing/repository.py. The repository falls back to
-- in-memory dicts when Supabase is not configured, so applying this schema
-- is only required for production multi-instance deployments.
--
-- Apply via:
--   psql "$SUPABASE_DB_URL" -f website/features/user_pricing/schema.sql
-- ============================================================================

create extension if not exists "pgcrypto";

-- ── billing_profiles ────────────────────────────────────────────────────────
create table if not exists public.pricing_billing_profiles (
    id              uuid primary key default gen_random_uuid(),
    render_user_id  text not null unique,
    email           text not null default '',
    phone           text not null default '',
    name            text not null default '',
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index if not exists pricing_billing_profiles_user_idx
    on public.pricing_billing_profiles (render_user_id);

-- ── pricing_orders (one row per checkout attempt, packs + subs) ─────────────
create table if not exists public.pricing_orders (
    id                          uuid primary key default gen_random_uuid(),
    payment_id                  text not null unique,
    render_user_id              text not null,
    product_id                  text not null,
    kind                        text not null check (kind in ('pack', 'subscription')),
    amount                      bigint not null check (amount >= 0),
    currency                    text not null default 'INR',
    status                      text not null default 'created'
                                    check (status in ('created', 'paid', 'failed', 'refunded')),
    plan_id                     text,
    period_id                   text,
    meter                       text,
    quantity                    integer,
    razorpay_order_id           text,
    razorpay_subscription_id    text,
    razorpay_payment_id         text,
    failure_reason              text,
    paid_at                     timestamptz,
    created_at                  timestamptz not null default now(),
    updated_at                  timestamptz not null default now()
);

create index if not exists pricing_orders_user_idx
    on public.pricing_orders (render_user_id, created_at desc);
create index if not exists pricing_orders_status_idx
    on public.pricing_orders (status);
create index if not exists pricing_orders_rzp_order_idx
    on public.pricing_orders (razorpay_order_id);
create index if not exists pricing_orders_rzp_payment_idx
    on public.pricing_orders (razorpay_payment_id);

-- ── pricing_subscriptions (current active subscription per user) ────────────
create table if not exists public.pricing_subscriptions (
    id                          uuid primary key default gen_random_uuid(),
    render_user_id              text not null unique,
    plan_id                     text not null,
    period_id                   text not null,
    status                      text not null default 'active'
                                    check (status in ('created', 'active', 'grace', 'cancelled', 'completed')),
    current_period_start        timestamptz not null default now(),
    current_period_end          timestamptz not null,
    razorpay_subscription_id    text,
    razorpay_payment_id         text,
    created_at                  timestamptz not null default now(),
    updated_at                  timestamptz not null default now()
);

create index if not exists pricing_subscriptions_user_idx
    on public.pricing_subscriptions (render_user_id);
create index if not exists pricing_subscriptions_status_idx
    on public.pricing_subscriptions (status, current_period_end);

-- ── pricing_balances (pack credits per user/meter) ──────────────────────────
create table if not exists public.pricing_balances (
    id              uuid primary key default gen_random_uuid(),
    render_user_id  text not null,
    meter           text not null,
    balance         bigint not null default 0 check (balance >= 0),
    updated_at      timestamptz not null default now(),
    unique (render_user_id, meter)
);

create index if not exists pricing_balances_user_idx
    on public.pricing_balances (render_user_id);

-- ── pricing_payment_events (webhook event log w/ idempotency) ───────────────
create table if not exists public.pricing_payment_events (
    id           uuid primary key default gen_random_uuid(),
    event_id     text not null unique,
    event_type   text not null,
    payment_id   text,
    payload      jsonb not null default '{}'::jsonb,
    created_at   timestamptz not null default now()
);

create index if not exists pricing_payment_events_payment_idx
    on public.pricing_payment_events (payment_id);
create index if not exists pricing_payment_events_type_idx
    on public.pricing_payment_events (event_type, created_at desc);

-- ── credit-add RPC (atomic upsert for pack fulfillment) ─────────────────────
create or replace function public.pricing_add_pack_credits(
    p_render_user_id text,
    p_meter          text,
    p_quantity       integer
) returns bigint
language plpgsql
security definer
as $$
declare
    new_balance bigint;
begin
    insert into public.pricing_balances (render_user_id, meter, balance, updated_at)
    values (p_render_user_id, p_meter, p_quantity, now())
    on conflict (render_user_id, meter)
    do update set
        balance    = pricing_balances.balance + excluded.balance,
        updated_at = now()
    returning balance into new_balance;
    return new_balance;
end;
$$;

-- ── updated_at trigger helper ───────────────────────────────────────────────
create or replace function public.pricing_touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists pricing_orders_touch on public.pricing_orders;
create trigger pricing_orders_touch
    before update on public.pricing_orders
    for each row execute function public.pricing_touch_updated_at();

drop trigger if exists pricing_subscriptions_touch on public.pricing_subscriptions;
create trigger pricing_subscriptions_touch
    before update on public.pricing_subscriptions
    for each row execute function public.pricing_touch_updated_at();

drop trigger if exists pricing_billing_profiles_touch on public.pricing_billing_profiles;
create trigger pricing_billing_profiles_touch
    before update on public.pricing_billing_profiles
    for each row execute function public.pricing_touch_updated_at();

-- ── RLS — enabled + service-role bypass via JWT role claim ──────────────────
alter table public.pricing_billing_profiles  enable row level security;
alter table public.pricing_orders            enable row level security;
alter table public.pricing_subscriptions     enable row level security;
alter table public.pricing_balances          enable row level security;
alter table public.pricing_payment_events    enable row level security;

-- service_role can read/write everything
do $$
begin
    if not exists (
        select 1 from pg_policies
        where schemaname = 'public' and tablename = 'pricing_orders' and policyname = 'service_role_all'
    ) then
        create policy service_role_all on public.pricing_orders
            for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
    end if;

    if not exists (
        select 1 from pg_policies
        where schemaname = 'public' and tablename = 'pricing_subscriptions' and policyname = 'service_role_all'
    ) then
        create policy service_role_all on public.pricing_subscriptions
            for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
    end if;

    if not exists (
        select 1 from pg_policies
        where schemaname = 'public' and tablename = 'pricing_balances' and policyname = 'service_role_all'
    ) then
        create policy service_role_all on public.pricing_balances
            for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
    end if;

    if not exists (
        select 1 from pg_policies
        where schemaname = 'public' and tablename = 'pricing_payment_events' and policyname = 'service_role_all'
    ) then
        create policy service_role_all on public.pricing_payment_events
            for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
    end if;

    if not exists (
        select 1 from pg_policies
        where schemaname = 'public' and tablename = 'pricing_billing_profiles' and policyname = 'service_role_all'
    ) then
        create policy service_role_all on public.pricing_billing_profiles
            for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
    end if;
end $$;

-- end of schema
