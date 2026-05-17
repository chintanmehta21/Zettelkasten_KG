-- supabase/website/_v2/44_functional_gates.sql
--
-- Phase 9 functional gates: multi-period quota enforcement, config-driven.
-- Authorized in PR #18 ("exec functional_gates"). Operator approvals on file:
--   A1 Phase 9 implementation (replaces legacy fail-open stub).
--   A2 New tables for rolling per-profile counters + idempotency ledger.
--   A3 Atomic reserve-and-consume RPC; caps passed from Python config.
--   A4 No refund on pipeline failure (matches Kasten-deletion semantics).
--   A5 min(remaining_day, remaining_week, remaining_month, remaining_lifetime).
--   B2 Free-plan auto-seed trigger on new profiles.
--
-- Design note (operator-locked 2026-05-17): plan caps are NOT stored in the
-- DB. The source of truth is `website/features/functional_gates/config.py`.
-- The Python gate reads caps from that module and passes them to this RPC
-- as a jsonb argument. Changing a cap = editing the Python file + redeploy;
-- no DB migration required. This keeps cap policy fully dynamic and ensures
-- the SQL layer never disagrees with the application layer.
--
-- Supersedes (DROPs) these stale Phase-8 pricing surfaces:
--   * billing.pricing_consume_entitlement(uuid, text, text) -- never called
--   * billing.pricing_entitlement_consumption                -- never written
--   * billing.pricing_plan_entitlements (monthly_limit only) -- empty, wrong shape
--     (we do NOT recreate it — config.py is the source of truth)

BEGIN;

-- ── 1. DROP stale Phase-8 pricing objects ────────────────────────────────
DROP FUNCTION IF EXISTS billing.pricing_consume_entitlement(uuid, text, text);
DROP TABLE IF EXISTS billing.pricing_entitlement_consumption;
DROP TABLE IF EXISTS billing.pricing_plan_entitlements;

-- ── 2. Rolling per-profile usage counters ─────────────────────────────────
CREATE TABLE billing.pricing_usage_counters (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id    uuid NOT NULL REFERENCES core.profiles(id) ON DELETE CASCADE,
    feature       text NOT NULL,
    granularity   text NOT NULL,
    period_key    text NOT NULL,
    count         bigint NOT NULL DEFAULT 0 CHECK (count >= 0),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (profile_id, feature, granularity, period_key)
);

CREATE INDEX pricing_usage_counters_lookup_idx
    ON billing.pricing_usage_counters (profile_id, feature, granularity, period_key);

COMMENT ON TABLE billing.pricing_usage_counters IS
    'Aggregated usage counters per (profile, feature, granularity, period_key). '
    'period_key formats: day=YYYY-MM-DD, week=IYYY-"W"IW, month=YYYY-MM, lifetime=*. '
    'Caps are NOT stored here; they live in functional_gates/config.py.';

-- ── 3. Idempotency ledger ──────────────────────────────────────────────────
CREATE TABLE billing.pricing_action_ledger (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id    uuid NOT NULL REFERENCES core.profiles(id) ON DELETE CASCADE,
    feature       text NOT NULL,
    action_id     text NOT NULL,
    source        text NOT NULL CHECK (source IN ('plan','wallet')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (profile_id, feature, action_id)
);

COMMENT ON TABLE billing.pricing_action_ledger IS
    'Idempotency ledger for reserve_and_consume. Same (profile, feature, action_id) '
    'returns the original outcome and never double-charges.';

-- ── 4. Atomic reserve-and-consume RPC (caps from caller) ───────────────────
-- p_caps shape (any keys may be NULL or omitted):
--   { "day": 2|null, "week": 10|null, "month": 30|null, "lifetime": 1|null }
-- p_wallet_meter is the pricing_balances meter name for pack credits.
CREATE OR REPLACE FUNCTION billing.pricing_reserve_and_consume(
    p_profile_id   uuid,
    p_feature      text,
    p_action_id    text,
    p_caps         jsonb,
    p_wallet_meter text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_now           timestamptz := now();
    v_day_key       text;
    v_week_key      text;
    v_month_key     text;
    v_used_day      bigint;
    v_used_week     bigint;
    v_used_month    bigint;
    v_used_lifetime bigint;
    v_lim_day       integer;
    v_lim_week      integer;
    v_lim_month     integer;
    v_lim_lifetime  integer;
    v_rem_plan      integer;
    v_wallet        bigint;
    v_source        text;
    v_existing      text;
    v_any_cap       boolean;
BEGIN
    IF p_profile_id IS NULL OR p_feature IS NULL OR p_action_id IS NULL
       OR length(p_action_id) = 0 OR p_caps IS NULL OR p_wallet_meter IS NULL THEN
        RAISE EXCEPTION 'invalid_argument' USING ERRCODE = '22023';
    END IF;

    -- Idempotency.
    SELECT source INTO v_existing
      FROM billing.pricing_action_ledger
     WHERE profile_id = p_profile_id
       AND feature    = p_feature
       AND action_id  = p_action_id;
    IF v_existing IS NOT NULL THEN
        RETURN jsonb_build_object(
            'allowed', true,
            'idempotent', true,
            'source', v_existing,
            'reason', 'ok'
        );
    END IF;

    v_day_key   := to_char(v_now AT TIME ZONE 'UTC', 'YYYY-MM-DD');
    v_week_key  := to_char(v_now AT TIME ZONE 'UTC', 'IYYY-"W"IW');
    v_month_key := to_char(v_now AT TIME ZONE 'UTC', 'YYYY-MM');

    -- Extract caps from jsonb. jsonb null and missing keys both → NULL.
    v_lim_day      := NULLIF(p_caps->>'day',      '')::integer;
    v_lim_week     := NULLIF(p_caps->>'week',     '')::integer;
    v_lim_month    := NULLIF(p_caps->>'month',    '')::integer;
    v_lim_lifetime := NULLIF(p_caps->>'lifetime', '')::integer;

    -- Read counters in a single roundtrip.
    SELECT coalesce(sum(case when granularity='day'      and period_key = v_day_key   then count end), 0),
           coalesce(sum(case when granularity='week'     and period_key = v_week_key  then count end), 0),
           coalesce(sum(case when granularity='month'    and period_key = v_month_key then count end), 0),
           coalesce(sum(case when granularity='lifetime' and period_key = '*'         then count end), 0)
      INTO v_used_day, v_used_week, v_used_month, v_used_lifetime
      FROM billing.pricing_usage_counters
     WHERE profile_id = p_profile_id AND feature = p_feature;

    v_any_cap := v_lim_day IS NOT NULL OR v_lim_week IS NOT NULL
              OR v_lim_month IS NOT NULL OR v_lim_lifetime IS NOT NULL;

    IF v_any_cap THEN
        v_rem_plan := greatest(0, least(
            case when v_lim_day      is not null then v_lim_day      - v_used_day::int      else 2147483647 end,
            case when v_lim_week     is not null then v_lim_week     - v_used_week::int     else 2147483647 end,
            case when v_lim_month    is not null then v_lim_month    - v_used_month::int    else 2147483647 end,
            case when v_lim_lifetime is not null then v_lim_lifetime - v_used_lifetime::int else 2147483647 end
        ));
    ELSE
        -- No plan caps configured: plan grants nothing for this feature.
        v_rem_plan := 0;
    END IF;

    SELECT balance INTO v_wallet
      FROM billing.pricing_balances
     WHERE profile_id = p_profile_id AND meter = p_wallet_meter;
    v_wallet := coalesce(v_wallet, 0);

    IF v_rem_plan > 0 THEN
        v_source := 'plan';

        IF v_lim_day IS NOT NULL THEN
            INSERT INTO billing.pricing_usage_counters
                (profile_id, feature, granularity, period_key, count)
            VALUES (p_profile_id, p_feature, 'day', v_day_key, 1)
            ON CONFLICT (profile_id, feature, granularity, period_key)
            DO UPDATE SET count = pricing_usage_counters.count + 1,
                          updated_at = now();
        END IF;
        IF v_lim_week IS NOT NULL THEN
            INSERT INTO billing.pricing_usage_counters
                (profile_id, feature, granularity, period_key, count)
            VALUES (p_profile_id, p_feature, 'week', v_week_key, 1)
            ON CONFLICT (profile_id, feature, granularity, period_key)
            DO UPDATE SET count = pricing_usage_counters.count + 1,
                          updated_at = now();
        END IF;
        IF v_lim_month IS NOT NULL THEN
            INSERT INTO billing.pricing_usage_counters
                (profile_id, feature, granularity, period_key, count)
            VALUES (p_profile_id, p_feature, 'month', v_month_key, 1)
            ON CONFLICT (profile_id, feature, granularity, period_key)
            DO UPDATE SET count = pricing_usage_counters.count + 1,
                          updated_at = now();
        END IF;
        IF v_lim_lifetime IS NOT NULL THEN
            INSERT INTO billing.pricing_usage_counters
                (profile_id, feature, granularity, period_key, count)
            VALUES (p_profile_id, p_feature, 'lifetime', '*', 1)
            ON CONFLICT (profile_id, feature, granularity, period_key)
            DO UPDATE SET count = pricing_usage_counters.count + 1,
                          updated_at = now();
        END IF;
    ELSIF v_wallet > 0 THEN
        v_source := 'wallet';
        PERFORM billing.pricing_deduct_pack_credits(p_profile_id, p_wallet_meter, 1);
        v_wallet := v_wallet - 1;
    ELSE
        RETURN jsonb_build_object(
            'allowed', false,
            'idempotent', false,
            'source', 'none',
            'reason', 'quota_exhausted',
            'remaining_plan', 0,
            'remaining_wallet', 0,
            'caps', p_caps,
            'used', jsonb_build_object(
                'day', v_used_day, 'week', v_used_week,
                'month', v_used_month, 'lifetime', v_used_lifetime
            )
        );
    END IF;

    INSERT INTO billing.pricing_action_ledger
        (profile_id, feature, action_id, source)
    VALUES (p_profile_id, p_feature, p_action_id, v_source)
    ON CONFLICT (profile_id, feature, action_id) DO NOTHING;

    RETURN jsonb_build_object(
        'allowed', true,
        'idempotent', false,
        'source', v_source,
        'reason', 'ok',
        'remaining_plan', case when v_source='plan' then v_rem_plan - 1 else v_rem_plan end,
        'remaining_wallet', v_wallet
    );
END
$$;

GRANT EXECUTE ON FUNCTION billing.pricing_reserve_and_consume(uuid, text, text, jsonb, text)
    TO authenticated, service_role;

COMMENT ON FUNCTION billing.pricing_reserve_and_consume(uuid, text, text, jsonb, text) IS
    'Atomic reserve-and-consume gate. Idempotent on (profile_id, feature, action_id). '
    'Caps come from the caller (Python functional_gates.config); never from the DB. '
    'No refund on caller failure (matches Kasten-deletion semantics).';

-- ── 5. Quota snapshot RPC (read-only, UI display) ─────────────────────────
CREATE OR REPLACE FUNCTION billing.pricing_get_quota_snapshot(
    p_profile_id   uuid,
    p_feature      text,
    p_caps         jsonb,
    p_wallet_meter text
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_now           timestamptz := now();
    v_day_key       text;
    v_week_key      text;
    v_month_key     text;
    v_used_day      bigint;
    v_used_week     bigint;
    v_used_month    bigint;
    v_used_lifetime bigint;
    v_lim_day       integer;
    v_lim_week      integer;
    v_lim_month     integer;
    v_lim_lifetime  integer;
    v_wallet        bigint;
    v_rem           integer;
    v_any_cap       boolean;
BEGIN
    v_day_key   := to_char(v_now AT TIME ZONE 'UTC', 'YYYY-MM-DD');
    v_week_key  := to_char(v_now AT TIME ZONE 'UTC', 'IYYY-"W"IW');
    v_month_key := to_char(v_now AT TIME ZONE 'UTC', 'YYYY-MM');

    v_lim_day      := NULLIF(p_caps->>'day',      '')::integer;
    v_lim_week     := NULLIF(p_caps->>'week',     '')::integer;
    v_lim_month    := NULLIF(p_caps->>'month',    '')::integer;
    v_lim_lifetime := NULLIF(p_caps->>'lifetime', '')::integer;

    SELECT coalesce(sum(case when granularity='day'      and period_key = v_day_key   then count end), 0),
           coalesce(sum(case when granularity='week'     and period_key = v_week_key  then count end), 0),
           coalesce(sum(case when granularity='month'    and period_key = v_month_key then count end), 0),
           coalesce(sum(case when granularity='lifetime' and period_key = '*'         then count end), 0)
      INTO v_used_day, v_used_week, v_used_month, v_used_lifetime
      FROM billing.pricing_usage_counters
     WHERE profile_id = p_profile_id AND feature = p_feature;

    SELECT balance INTO v_wallet
      FROM billing.pricing_balances
     WHERE profile_id = p_profile_id AND meter = p_wallet_meter;
    v_wallet := coalesce(v_wallet, 0);

    v_any_cap := v_lim_day IS NOT NULL OR v_lim_week IS NOT NULL
              OR v_lim_month IS NOT NULL OR v_lim_lifetime IS NOT NULL;
    IF v_any_cap THEN
        v_rem := greatest(0, least(
            case when v_lim_day      is not null then v_lim_day      - v_used_day::int      else 2147483647 end,
            case when v_lim_week     is not null then v_lim_week     - v_used_week::int     else 2147483647 end,
            case when v_lim_month    is not null then v_lim_month    - v_used_month::int    else 2147483647 end,
            case when v_lim_lifetime is not null then v_lim_lifetime - v_used_lifetime::int else 2147483647 end
        ));
    ELSE
        v_rem := 0;
    END IF;

    RETURN jsonb_build_object(
        'feature', p_feature,
        'caps', p_caps,
        'used', jsonb_build_object(
            'day', v_used_day, 'week', v_used_week,
            'month', v_used_month, 'lifetime', v_used_lifetime
        ),
        'remaining_plan', v_rem,
        'remaining_wallet', v_wallet,
        'effective_available', v_rem + v_wallet
    );
END
$$;

GRANT EXECUTE ON FUNCTION billing.pricing_get_quota_snapshot(uuid, text, jsonb, text)
    TO authenticated, service_role;

-- ── 6. Auth-user / profile → Free subscription seed ───────────────────────
CREATE OR REPLACE FUNCTION billing.seed_free_subscription_on_profile()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    INSERT INTO billing.pricing_subscriptions
        (profile_id, plan_id, status, current_period_start, provider_payload)
    VALUES
        (NEW.id, 'free', 'active', now(), '{"source": "auto_signup"}'::jsonb)
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS seed_free_subscription_on_profile ON core.profiles;
CREATE TRIGGER seed_free_subscription_on_profile
AFTER INSERT ON core.profiles
FOR EACH ROW
EXECUTE FUNCTION billing.seed_free_subscription_on_profile();

-- ── 7. Backfill Free subscription for existing profiles ──────────────────
INSERT INTO billing.pricing_subscriptions
    (profile_id, plan_id, status, current_period_start, provider_payload)
SELECT p.id, 'free', 'active', now(), '{"source": "backfill_44"}'::jsonb
  FROM core.profiles p
 WHERE NOT EXISTS (
        SELECT 1 FROM billing.pricing_subscriptions s
         WHERE s.profile_id = p.id
   )
ON CONFLICT DO NOTHING;

-- ── 8. RLS ────────────────────────────────────────────────────────────────
ALTER TABLE billing.pricing_usage_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing.pricing_action_ledger  ENABLE ROW LEVEL SECURITY;

CREATE POLICY pricing_usage_counters_service ON billing.pricing_usage_counters
    FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY pricing_action_ledger_service ON billing.pricing_action_ledger
    FOR ALL TO service_role USING (true) WITH CHECK (true);

NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';

COMMIT;
