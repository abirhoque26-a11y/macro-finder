-- Macro Mastery — subscription state
-- Run once in the Supabase SQL Editor, in a NEW snippet.
--
-- Only the Stripe webhook writes to this table, using the service_role key,
-- which bypasses RLS. Users may READ their own row and nothing else — so a
-- signed-in user can never grant themselves Pro by calling the API directly.

create table public.subscriptions (
  user_id              uuid primary key references auth.users(id) on delete cascade,
  stripe_customer_id   text unique,
  stripe_subscription_id text unique,
  -- Stripe's own vocabulary, stored verbatim so it always matches the dashboard:
  -- trialing | active | past_due | canceled | incomplete | incomplete_expired | unpaid
  status               text not null default 'none',
  price_id             text,
  trial_end            timestamptz,
  current_period_end   timestamptz,
  cancel_at_period_end boolean not null default false,
  updated_at           timestamptz not null default now()
);

alter table public.subscriptions enable row level security;

-- Read-only, and only your own row. There is deliberately no insert/update/delete
-- policy: nothing a browser can do should ever write here.
create policy "subscriptions own select" on public.subscriptions
  for select using (auth.uid() = user_id);

-- Convenience view of "is this person entitled to Pro right now".
-- A trial counts as entitled; an expired period does not, even if Stripe has
-- not yet sent the cancellation webhook.
create or replace function public.is_pro(uid uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.subscriptions s
    where s.user_id = uid
      and s.status in ('trialing', 'active')
      and (s.current_period_end is null or s.current_period_end > now())
  );
$$;

grant execute on function public.is_pro(uuid) to authenticated, anon;
