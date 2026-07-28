/* POST /api/portal
 *
 * Opens Stripe's own billing portal so a subscriber can update their card,
 * see invoices, or cancel. Cancelling has to be as easy as subscribing —
 * that is both a UK consumer-law expectation and a Stripe requirement.
 *
 * Env vars: STRIPE_SECRET_KEY, SUPABASE_URL, SUPABASE_ANON_KEY,
 *           SUPABASE_SERVICE_ROLE_KEY, SITE_URL
 */

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
  const SUPABASE_URL = env('SUPABASE_URL').replace(/\/+$/, '');
  const SUPABASE_ANON_KEY = env('SUPABASE_ANON_KEY');
  const SUPABASE_SERVICE_ROLE_KEY = env('SUPABASE_SERVICE_ROLE_KEY');
  const SITE_URL = env('SITE_URL');

  try {
    const auth = req.headers.authorization || '';
    const token = auth.startsWith('Bearer ') ? auth.slice(7) : null;
    if (!token) return res.status(401).json({ error: 'Sign in first' });

    const who = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
      headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${token}` }
    });
    if (!who.ok) return res.status(401).json({ error: 'Sign in again' });
    const user = await who.json();

    /* Look the customer id up server-side from the signed-in user. Taking it
       from the request would let anyone open anyone else's billing portal. */
    const q = await fetch(
      `${SUPABASE_URL}/rest/v1/subscriptions?user_id=eq.${user.id}&select=stripe_customer_id`,
      {
        headers: {
          apikey: SUPABASE_SERVICE_ROLE_KEY,
          Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`
        }
      }
    );
    const rows = await q.json();
    const customer = rows && rows[0] && rows[0].stripe_customer_id;
    if (!customer) return res.status(404).json({ error: 'No subscription found' });

    const site = SITE_URL || `https://${req.headers.host}`;
    const r = await fetch('https://api.stripe.com/v1/billing_portal/sessions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${STRIPE_SECRET_KEY}`,
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: new URLSearchParams({ customer, return_url: site })
    });
    const session = await r.json();
    if (!r.ok) {
      console.error('stripe portal error', session);
      return res.status(502).json({ error: session.error?.message || 'Stripe rejected the request' });
    }
    return res.status(200).json({ url: session.url });
  } catch (err) {
    console.error('portal', err);
    return res.status(500).json({ error: 'Could not open billing portal' });
  }
};
