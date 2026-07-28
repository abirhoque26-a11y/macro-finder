/* POST /api/stripe-webhook
 *
 * The only thing that ever writes to the `subscriptions` table. Stripe tells us
 * a subscription started, renewed, lapsed or was cancelled, and we mirror that
 * into Supabase using the service_role key.
 *
 * Every request is signature-checked first. Without that, anyone who found this
 * URL could POST themselves a lifetime subscription.
 *
 * Env vars (set in Vercel):
 *   STRIPE_SECRET_KEY          sk_test_... / sk_live_...
 *   STRIPE_WEBHOOK_SECRET      whsec_...  (from the Stripe webhook endpoint)
 *   SUPABASE_URL               https://<ref>.supabase.co
 *   SUPABASE_SERVICE_ROLE_KEY  service_role key — bypasses RLS, server only
 */

const crypto = require('crypto');

// Stripe signs the exact bytes it sent, so the body must not be re-serialised.
module.exports.config = { api: { bodyParser: false } };

async function readRaw(req) {
  if (Buffer.isBuffer(req.body)) return req.body;
  if (typeof req.body === 'string') return Buffer.from(req.body, 'utf8');
  const chunks = [];
  for await (const chunk of req) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  return Buffer.concat(chunks);
}

/* Verifies Stripe's `t=…,v1=…` signature header. Rejects anything older than
   five minutes so a captured request cannot be replayed later. */
function verify(raw, header, secret) {
  if (!header) return false;
  const parts = Object.fromEntries(
    header.split(',').map(p => p.split('=', 2)).filter(p => p.length === 2)
  );
  const ts = parts.t;
  const sig = parts.v1;
  if (!ts || !sig) return false;
  if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) return false;

  const expected = crypto
    .createHmac('sha256', secret)
    .update(`${ts}.${raw.toString('utf8')}`, 'utf8')
    .digest('hex');
  const a = Buffer.from(expected, 'utf8');
  const b = Buffer.from(sig, 'utf8');
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

const iso = s => (s ? new Date(s * 1000).toISOString() : null);

async function upsert(row) {
  const { SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY } = process.env;
  const r = await fetch(`${SUPABASE_URL}/rest/v1/subscriptions?on_conflict=user_id`, {
    method: 'POST',
    headers: {
      apikey: SUPABASE_SERVICE_ROLE_KEY,
      Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
      'Content-Type': 'application/json',
      Prefer: 'resolution=merge-duplicates,return=minimal'
    },
    body: JSON.stringify({ ...row, updated_at: new Date().toISOString() })
  });
  if (!r.ok) throw new Error(`supabase upsert ${r.status}: ${await r.text()}`);
}

async function stripeGet(path) {
  const r = await fetch(`https://api.stripe.com/v1/${path}`, {
    headers: { Authorization: `Bearer ${process.env.STRIPE_SECRET_KEY}` }
  });
  if (!r.ok) throw new Error(`stripe ${path} ${r.status}`);
  return r.json();
}

/* The user id rides along in metadata (set at checkout). Older or unusual events
   may not carry it, so fall back to looking it up on the subscription. */
async function userIdFor(sub) {
  const direct = sub.metadata && sub.metadata.supabase_user_id;
  if (direct) return direct;
  try {
    const full = await stripeGet(`subscriptions/${sub.id}`);
    return (full.metadata && full.metadata.supabase_user_id) || null;
  } catch (e) {
    console.error('userIdFor', e.message);
    return null;
  }
}

module.exports = async (req, res) => {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).end();
  }
  const secret = process.env.STRIPE_WEBHOOK_SECRET;
  if (!secret || !process.env.SUPABASE_SERVICE_ROLE_KEY) {
    console.error('stripe-webhook: missing environment variables');
    return res.status(500).end();
  }

  let raw;
  try {
    raw = await readRaw(req);
  } catch (e) {
    console.error('raw body', e);
    return res.status(400).end();
  }

  if (!verify(raw, req.headers['stripe-signature'], secret)) {
    console.warn('stripe-webhook: bad signature');
    return res.status(400).json({ error: 'Invalid signature' });
  }

  let event;
  try {
    event = JSON.parse(raw.toString('utf8'));
  } catch (e) {
    return res.status(400).end();
  }

  try {
    const o = event.data.object;

    if (event.type === 'checkout.session.completed') {
      // client_reference_id is the Supabase user id we set when creating the session
      const uid = o.client_reference_id || (o.metadata && o.metadata.supabase_user_id);
      if (uid && o.subscription) {
        const sub = await stripeGet(`subscriptions/${o.subscription}`);
        await upsert({
          user_id: uid,
          stripe_customer_id: o.customer,
          stripe_subscription_id: sub.id,
          status: sub.status,
          price_id: sub.items?.data?.[0]?.price?.id || null,
          trial_end: iso(sub.trial_end),
          current_period_end: iso(sub.current_period_end),
          cancel_at_period_end: !!sub.cancel_at_period_end
        });
      }
    } else if (event.type.startsWith('customer.subscription.')) {
      const uid = await userIdFor(o);
      if (uid) {
        await upsert({
          user_id: uid,
          stripe_customer_id: o.customer,
          stripe_subscription_id: o.id,
          // a deleted subscription is 'canceled' regardless of its last status
          status: event.type === 'customer.subscription.deleted' ? 'canceled' : o.status,
          price_id: o.items?.data?.[0]?.price?.id || null,
          trial_end: iso(o.trial_end),
          current_period_end: iso(o.current_period_end),
          cancel_at_period_end: !!o.cancel_at_period_end
        });
      }
    }
    // Anything else we acknowledge and ignore — Stripe retries non-2xx forever.

    return res.status(200).json({ received: true });
  } catch (err) {
    // 500 tells Stripe to retry, which is what we want for a transient failure
    console.error('stripe-webhook handler', err);
    return res.status(500).json({ error: 'handler failed' });
  }
};
