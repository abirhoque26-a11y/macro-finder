/* POST /api/create-checkout
 *
 * Starts a Stripe Checkout session for Macro Mastery Pro, with a 3-day trial.
 *
 * The caller sends their Supabase access token, never a user id — we ask
 * Supabase who that token belongs to and use the answer. Trusting a user id
 * from the browser would let anyone start a subscription in someone else's name.
 *
 * Env vars (set in Vercel, never in the repo):
 *   STRIPE_SECRET_KEY       sk_test_... / sk_live_...
 *   STRIPE_PRICE_MONTHLY    price_...
 *   STRIPE_PRICE_YEARLY     price_...
 *   SUPABASE_URL            https://<ref>.supabase.co
 *   SUPABASE_ANON_KEY       the public anon key (used only to validate tokens)
 *   SITE_URL                https://www.macromastery.uk
 */

const TRIAL_DAYS = 3;

function form(obj, prefix, out) {
  out = out || new URLSearchParams();
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined || v === null) continue;
    const key = prefix ? `${prefix}[${k}]` : k;
    if (typeof v === 'object' && !Array.isArray(v)) form(v, key, out);
    else out.append(key, String(v));
  }
  return out;
}

/* Environment values get pasted by hand, and a stray leading space or trailing
   newline makes an HTTP header invalid — which fails as an opaque TypeError far
   from the cause. Trim everything on the way in. */
const env = n => (process.env[n] || '').trim();

module.exports = async (req, res) => {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const STRIPE_SECRET_KEY = env('STRIPE_SECRET_KEY');
  const STRIPE_PRICE_MONTHLY = env('STRIPE_PRICE_MONTHLY');
  const STRIPE_PRICE_YEARLY = env('STRIPE_PRICE_YEARLY');
  const SUPABASE_URL = env('SUPABASE_URL').replace(/\/+$/, '');
  const SUPABASE_ANON_KEY = env('SUPABASE_ANON_KEY');
  const SITE_URL = env('SITE_URL');

  if (!STRIPE_SECRET_KEY || !SUPABASE_URL || !SUPABASE_ANON_KEY) {
    console.error('create-checkout: missing environment variables');
    return res.status(500).json({ error: 'Server not configured' });
  }

  try {
    const body = typeof req.body === 'string' ? JSON.parse(req.body) : (req.body || {});
    const plan = body.plan === 'yearly' ? 'yearly' : 'monthly';
    const price = plan === 'yearly' ? STRIPE_PRICE_YEARLY : STRIPE_PRICE_MONTHLY;
    if (!price) return res.status(500).json({ error: 'Price not configured' });

    // Who is actually asking? Supabase is the authority, not the request body.
    const auth = req.headers.authorization || '';
    const token = auth.startsWith('Bearer ') ? auth.slice(7) : null;
    if (!token) return res.status(401).json({ error: 'Sign in first' });

    const who = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
      headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${token}` }
    });
    if (!who.ok) return res.status(401).json({ error: 'Sign in again' });
    const user = await who.json();
    if (!user || !user.id) return res.status(401).json({ error: 'Sign in again' });

    const site = SITE_URL || `https://${req.headers.host}`;
    const payload = form({
      mode: 'subscription',
      client_reference_id: user.id,
      customer_email: user.email,
      allow_promotion_codes: 'true',
      success_url: `${site}/?upgraded=1`,
      cancel_url: `${site}/?upgrade_cancelled=1`,
      line_items: { 0: { price, quantity: 1 } },
      subscription_data: {
        trial_period_days: TRIAL_DAYS,
        // carried onto the subscription object, so the webhook can identify the
        // user even on events that do not include the checkout session
        metadata: { supabase_user_id: user.id }
      },
      metadata: { supabase_user_id: user.id }
    });

    const r = await fetch('https://api.stripe.com/v1/checkout/sessions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${STRIPE_SECRET_KEY}`,
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: payload
    });
    const session = await r.json();
    if (!r.ok) {
      console.error('stripe checkout error', session);
      return res.status(502).json({ error: session.error?.message || 'Stripe rejected the request' });
    }
    return res.status(200).json({ url: session.url });
  } catch (err) {
    // Detail goes to the Vercel log, not to the browser — an error message on a
    // public endpoint can leak how the backend is put together.
    console.error('create-checkout', err);
    return res.status(500).json({ error: 'Could not start checkout' });
  }
};
