# End-to-End Razorpay Integration Architecture for Zettelkasten.in

## 1. Overview and requirements

Zettelkasten.in is a FastAPI-based web application that serves a static front-end (pricing, home, zettels, kastens pages) and a set of API routes for summarization, RAG, and user features under `website/api/*`. The goal is to integrate Razorpay as the sole payments provider for:

- **Subscriptions**: Basic and Max plans with monthly, quarterly, and yearly billing.
- **Custom one-time packs**: Zettel packs, Kasten packs, and optional RAG question packs.

The solution must:

- Support **Indian UPI** (intent, QR, UPI apps) and **Indian cards/netbanking** for domestic users.
- Support **international cards** and international payment methods for foreign users.
- Use **industry-standard Razorpay APIs** (Payment Gateway + Subscriptions).
- Minimize tax and payment processing costs within the constraints of Indian regulation and Razorpay’s fee structure.

Razorpay is widely considered the default converged payment gateway for Indian businesses, with API coverage for UPI, cards, netbanking, wallets, BNPL, payouts, and subscriptions. Razorpay’s international offering supports 100–135+ currencies across its Payment Gateway, Payment Pages, Payment Links, and Subscriptions products, while settling to Indian merchants with transparent platform fees.[^1][^2][^3][^4]

## 2. Razorpay capabilities and pricing relevant to Zettelkasten.in

### 2.1 Domestic payments

For an Indian SaaS product, Razorpay’s **Standard Plan** typically charges around **2% + GST** on domestic transactions (UPI, cards, netbanking, wallets), with no setup or monthly fees. Key domestic methods:[^5][^6][^1]

- **UPI**: Supports PhonePe, Google Pay, Paytm, BHIM, and 40+ banks for real-time payments. Razorpay charges a ~2% platform fee for UPI even though MDR is officially zero on UPI/RuPay from the government; GST applies to the platform fee, not the full transaction amount.[^7][^6][^5][^1]
- **Cards**: Visa, Mastercard, RuPay debit/credit, with typical fees ~2% + GST for standard consumer cards.[^6][^5][^1]
- **Netbanking**: 50–100+ Indian banks at similar fee levels.[^8][^5]

Razorpay Subscriptions and Razorpay UPI Autopay allow recurring charges via **UPI mandates** and **card tokenisation**, meeting RBI’s e-mandate requirements.[^9][^10][^11][^7]

### 2.2 International payments

Razorpay supports **international cards** and international payment methods, with platform fees around **3% + GST** for international card transactions and 3.5% for alternative methods; international bank transfers via their MoneySaver export account start around 1% + GST. Features include:[^12][^5][^6]

- Acceptance of cards issued by foreign banks across 100–135+ currencies (USD, EUR, GBP, AED, SGD, etc.).[^2][^3][^4]
- Multi-currency support across Payment Gateway, Subscriptions, Payment Links, and other products.[^3][^2][^12]
- Partnership with **PayPal** so Indian merchants can accept PayPal payments through Razorpay with minimal extra integration, giving access to 200+ markets.[^13]

For Zettelkasten.in, a pragmatic baseline is:

- Bill **all plans and packs in INR** and let Razorpay handle FX for foreign cardholders and wallets.
- Enable international cards and PayPal (via Razorpay integration) as needed once there is sufficient global traffic.

### 2.3 Tax and cost implications

Razorpay’s platform fee is a percentage of the transaction amount, and **GST at 18% applies only to this fee**, not the full transaction value. There is no setup fee, no annual maintenance, and no monthly subscription fee on the standard plan; you pay only per transaction. To minimise total cost:[^5][^1][^6][^8]

- Prefer domestic UPI and cards for Indian customers (2% + GST vs 3%+ for international cards).[^1][^6][^5]
- Avoid using separate third-party aggregators on top of Razorpay, which would add another fee layer.
- Keep all billing in INR; Razorpay’s international support handles FX without you being directly exposed to additional PSP markup.[^4][^2][^3]

## 3. Mapping Razorpay to the Zettelkasten_KG architecture

### 3.1 Existing web structure

`website/app.py` reveals the key structure:

- Static UI:
  - `/pricing` → `PRICING_DIR / index.html` with supporting CSS/JS under `/pricing/css` and `/pricing/js`.
  - `/home`, `/home/zettels`, `/home/kastens` etc. for the signed-in area.
- API routes:
  - Included via `app.include_router(api_router)`, `chat_router`, `engine_v2_router`, etc.
- FastAPI app factory `create_app()` wires everything together.

Best practice for payments is to:

- Add a new router: `website/api/payments_routes.py`, exposing endpoints under `/api/payments`.
- Include it in `create_app()` with `app.include_router(payments_router, prefix="/api/payments", tags=["payments"])`.

This keeps all sensitive Razorpay integration logic server-side and separates it from the rest of the feature code.

### 3.2 High-level components

The Razorpay integration introduces the following components:

- **Frontend**: Existing pricing and account pages, plus lightweight JS to call `/api/payments/*` and then hand over to Razorpay Checkout.
- **Payments Service (FastAPI router)**: Responsible for creating Razorpay Orders, Subscriptions/Plans/Mandates and handling webhooks.
- **Billing Data Model**: Tables/collections to store users, subscriptions, invoices, payment events, and credit balances.
- **Razorpay APIs**:
  - Payment Gateway Orders API for one-time packs.
  - Subscriptions API (including UPI Autopay and card mandates) for recurring plans.[^11][^7][^9]
- **Webhooks endpoint** for asynchronous events (payment success, failure, subscription renewal, mandate updates).[^14]

## 4. Subscription architecture with Razorpay

### 4.1 Plan and product modelling

Define internal plans in your backend, e.g. in `website/api/billing_config.py`:

- `basic_monthly`, `basic_quarterly`, `basic_yearly`.
- `max_monthly`, `max_quarterly`, `max_yearly`.

Each plan object includes:

- `display_name` (e.g., "Basic Monthly").
- `internal_id` (string used in URLs and DB).
- `amount_in_inr` (list price and launch promo price).
- `billing_cycle` (MONTHLY, QUARTERLY, YEARLY).
- `features` (caps for zettels, kastens, questions).
- `razorpay_plan_id` (optional, if you pre-create plans in Razorpay dashboard).

You can use either of two patterns:

1. **Plan objects in Razorpay**:
   - Create Plans in Razorpay dashboard with amount, currency (INR), interval, and frequency.
   - Use Razorpay Subscriptions API to create subscriptions referencing these plan IDs for each user.

2. **Plan-less subscriptions**:
   - Directly create subscriptions with amount and interval per user without pre-defined plans.

Given you have a small, fixed set of plans, using Razorpay Plans (pattern 1) keeps billing logic simpler.

### 4.2 Payment methods for subscriptions

For recurring plans, Razorpay Subscriptions can use:[^10][^7][^9][^11]

- **UPI Autopay** (UPI 2.0 mandates up to ₹15,000 per cycle for generic categories, with higher limits for certain categories).
- **Card tokenised mandates** (credit and debit cards with RBI e-mandate compliance).
- **eMandates (NACH)** for bank account-based mandates (optional).

You can configure Subscriptions to allow both UPI Autopay and cards so the user chooses their preferred method at the mandate authorisation step.

### 4.3 Backend subscription endpoints

Create `website/api/payments_routes.py` with endpoints such as:

1. `POST /api/payments/subscriptions/create`
   - Input: `{ "plan_id": "basic_monthly" }`.
   - Steps:
     - Validate the authenticated user using your existing auth (Supabase Auth and session cookies/JWT).
     - Look up plan configuration; determine the **effective amount** based on whether launch pricing is active.
     - Option A: If using Razorpay Plans, call Razorpay Subscriptions API with:
       - `plan_id` = plan’s Razorpay plan ID.
       - `customer_notify` = True.
       - `total_count` = number of billing cycles (or `-1` for until cancelled, depending on your policy).
       - `notes` = { user_id, plan_id }.
     - Option B: If not using Plans, pass `amount`, `currency = "INR"`, `period = "monthly"`, etc.
     - Razorpay returns a `subscription_id` and `short_url` for mandate authorisation.
     - Save a provisional subscription record in your DB with status `created`.
     - Return JSON: `{ subscription_id, auth_url: short_url }` to the frontend.

2. `POST /api/payments/subscriptions/cancel`
   - Input: `{ "subscription_id": "sub_xxx" }`.
   - Steps:
     - Validate user owns this subscription.
     - Call Razorpay cancel subscription API.
     - Mark subscription as `cancelled` in DB, optionally let access continue until the current period end.

3. `POST /api/payments/subscriptions/webhook`
   - This is the Razorpay webhook endpoint (no auth; use signature verification via `X-Razorpay-Signature`).
   - Events to handle:
     - `subscription.activated`: Set subscription status to `active`; start entitlements.
     - `subscription.charged`: Record successful billing cycle; extend expiry.
     - `subscription.halted` / `subscription.pending`: Handle payment failures by sending warning emails and starting a grace period.
     - `subscription.cancelled` / `subscription.completed`: Mark as inactive.
   - Use idempotency (e.g., store last processed `event_id`) to avoid double-processing.

A minimal DB schema for subscriptions could include:

- `subscriptions` table:
  - `id` (internal UUID).
  - `user_id`.
  - `plan_id`.
  - `razorpay_subscription_id`.
  - `status` (`created`, `active`, `grace`, `cancelled`, `completed`).
  - `current_period_start`, `current_period_end`.
  - `created_at`, `updated_at`.

- `subscription_events` table for audit:
  - `id`, `subscription_id`, `event_type`, `payload`, `created_at`.

### 4.4 Front-end subscription flow

On the `/pricing` page, the JS already has a context for plan cards. For each “Subscribe” button:

1. User clicks "Subscribe Basic Monthly".
2. JS calls `POST /api/payments/subscriptions/create` with `plan_id`.
3. Backend returns `{ auth_url }`.
4. Front-end performs `window.location = auth_url` (or opens in new tab) to Razorpay’s subscription checkout.
5. User authorises UPI Autopay or card mandate.
6. Razorpay redirects back to your success/failure URL.
7. Backend relies on webhooks for final confirmation and updates user’s subscription state.

For UPI Autopay, Razorpay’s flow includes showing supported UPI apps and banks, user authenticates with UPI PIN once, then future debits are automatic.[^7][^9][^10][^11]

## 5. One-time custom packs with Razorpay Payment Gateway

### 5.1 Use Orders + Checkout instead of Subscriptions

For Zettel/Kasten packs and RAG question top-ups, use **Razorpay Orders** with Razorpay Checkout:

- Orders represent a one-time payment intent with amount in INR.
- Razorpay Checkout supports UPI, cards, netbanking, wallets, and (once configured) PayPal via Razorpay’s international payment integrations.[^13][^6][^1]

### 5.2 Backend endpoints for orders

Add to `payments_routes.py`:

1. `POST /api/payments/orders/create`
   - Input: `{ "pack_id": "zettel_10" }`.
   - Steps:
     - Validate authenticated user.
     - Lookup pack configuration – determine amount and description (consider launch vs list pricing).
     - Create Razorpay Order via API with:
       - `amount` in paise (e.g., 9900 for ₹99).
       - `currency = "INR"`.
       - `receipt` = unique receipt ID (e.g., `userId_packId_timestamp`).
       - `notes` = { user_id, pack_id }.
     - Razorpay returns `order_id`.
     - Return JSON: `{ order_id, amount, currency }` plus your Razorpay `key_id` for Checkout.

2. `POST /api/payments/orders/webhook`
   - Razorpay sends events for `payment.captured`, `payment.failed`, etc.
   - Verify signature with webhook secret.
   - On `payment.captured`:
     - Extract `order_id` and `notes` (`user_id`, `pack_id`).
     - Mark internal order as `paid`.
     - Credit user’s Zettel/Kasten/question balance according to `pack_id`.

DB schema for orders can include:

- `orders` table:
  - `id` (internal).
  - `user_id`.
  - `pack_id`.
  - `razorpay_order_id`.
  - `razorpay_payment_id`.
  - `status` (`created`, `paid`, `failed`, `refunded`).
  - `amount`, `currency`.
  - `created_at`, `updated_at`.

### 5.3 Front-end order flow

On pricing or in-app purchase UI:

1. User selects a pack (ex: 10 Zettels pack).
2. JS calls `POST /api/payments/orders/create` with `pack_id` and receives `{ order_id, amount, currency, key_id }`.
3. JS triggers Razorpay Checkout (via `Razorpay` JS object) with:
   - `key` = `key_id`.
   - `amount`, `currency`.
   - `order_id`.
   - `prefill` with user’s name/email.
   - Success handler that calls your backend `POST /api/payments/orders/verify` endpoint (optional) to confirm.
4. Razorpay handles payment method selection:
   - UPI (intent, QR, VPA).
   - Domestic and international cards.
   - Netbanking, wallets, and PayPal (if enabled via Razorpay’s integration).[^5][^13][^1]
5. Webhooks update your DB as the source of truth; the frontend can poll your backend for final status.

## 6. End-to-end architecture design

### 6.1 Component diagram (conceptual)

- **Browser (User)**
  - Visits `/pricing`, `/home`.
  - Initiates subscription or order.

- **FastAPI Backend (Zettelkasten_KG)**
  - Routes: `/api/payments/subscriptions/*`, `/api/payments/orders/*`.
  - Uses Razorpay SDK or direct REST calls with `key_id` and `key_secret`.
  - Stores subscriptions, orders, and payment events in DB/Supabase.
  - Updates user entitlements (caps, credits) on successful payments.

- **Razorpay Platform**
  - Payment Gateway and Checkout (hosted UI).
  - Subscriptions and UPI Autopay mandates.
  - Webhooks sending events back to backend.

- **Database (Supabase / Postgres)**
  - `users`, `subscriptions`, `orders`, `balance` tables.
  - Payment event logs for audit.

### 6.2 Request flows

**Subscription creation flow**:

1. `GET /pricing` → render page.
2. User clicks "Subscribe Basic Monthly".
3. `POST /api/payments/subscriptions/create` → backend creates Razorpay subscription, stores record, returns `auth_url`.
4. Client redirects to `auth_url` (Razorpay subscription checkout).
5. User authorises mandate via UPI or card.
6. Razorpay triggers `subscription.activated` webhook. Backend:
   - Verifies signature.
   - Marks subscription `active` and sets `current_period_end`.
   - Updates user’s caps in `user_profile` / billing tables.

**Subscription renewal flow**:

1. At renewal time, Razorpay charges the mandate.
2. On success, Razorpay sends `subscription.charged` / `payment.captured` for that subscription.
3. Backend extends `current_period_end`, logs event.
4. On failure, Razorpay retries as per its rules; after repeated failures, sends `subscription.halted`/`pending`, backend may put user into `grace` state.

**One-time pack purchase flow**:

1. User selects pack.
2. `POST /api/payments/orders/create` → backend creates Razorpay Order.
3. JS opens Razorpay Checkout with `order_id`.
4. User pays via UPI/cards/netbanking/PayPal.
5. Razorpay sends `payment.captured` webhook.
6. Backend credits user balances; frontend polls backend or listens to `orders/verify` for success.

## 7. Minimising tax and other payment costs

### 7.1 What cannot be optimised away

- **GST at 18%** is applied on Razorpay’s platform fees; this is mandatory and cannot be avoided.[^6][^5]
- MDR and platform fees for domestic and international payments are determined by Razorpay pricing; your only lever is negotiating volume-based pricing when your GMV is high enough.[^8][^1][^5]

### 7.2 Practical strategies within Razorpay’s framework

1. **Keep Razorpay as the only PSP** at this stage
   - Avoid stacking Stripe/PayPal separately on top of Razorpay for the same flows, which would add additional fees and complexity.
   - Use Razorpay’s own PayPal integration for international buyers when needed.[^13]

2. **Bill in INR, let Razorpay handle FX**
   - Maintain all list and launch prices in INR.
   - Razorpay supports 100–135+ currencies and handles currency conversion for international cards and methods.[^2][^3][^4]
   - This avoids signing separate foreign merchant agreements or creating multiple PSP contracts.

3. **Encourage low-cost methods for Indian users**
   - Highlight UPI and RuPay debit/card options (which may have lower effective costs) in your UX copy, even though Razorpay charges a roughly flat 2% platform fee for most domestic methods.[^6][^5]
   - You can use small discounts or loyalty perks for users who pay via UPI to nudge them away from higher-cost international card transactions.

4. **Use Subscriptions + UPI Autopay for recurring users**
   - Subscription plus UPI Autopay simplifies recurring collections and reduces failed payment overhead compared to manual renewals.[^9][^10][^11][^7]
   - This saves indirect operational cost (support, churn), which matters more than minor MDR differences.

5. **Monitor method mix and negotiate when large**
   - Use Razorpay dashboard and your own logs to track share of UPI vs cards vs international.
   - Once monthly GMV crosses Razorpay’s “Enterprise” thresholds, negotiate custom rates.[^8][^5]

## 8. Security, reliability, and operational best practices

- **Use Razorpay Checkout** (not custom card forms) to keep card/UPI data off your servers and minimize PCI scope.[^1][^8]
- **Verify all webhooks** using `X-Razorpay-Signature` and a shared webhook secret; treat webhook data as the source of truth and make UI callbacks secondary.
- **Implement idempotency** on subscription and order event handlers (e.g., using `event_id` and `razorpay_payment_id`), so retried events or duplicate webhooks do not double-credit user accounts.[^14]
- **Log everything**: For each payment, store raw webhook payloads and internal state transitions. This is invaluable for debugging disputes and handling chargebacks.
- **Graceful downgrade and grace periods**: For subscriptions, implement a small grace period on renewal failure, consistent with Razorpay’s retry schedule, to avoid instant hard cutoffs.[^10][^9][^14]
- **Key management**: Keep `key_id` and `key_secret` in environment variables or a secret manager; never embed them into client-side JS.

This architecture allows Zettelkasten.in to integrate Razorpay cleanly into its existing FastAPI web stack, supporting your subscription and custom pricing models with UPI, domestic and international cards, and PayPal, while keeping taxes and gateway costs as low as realistically possible for an Indian SaaS business.[^7][^5][^1][^6]

---

## References

1. [Razorpay API - DataGlobeHub](https://dataglobehub.com/api-finder/razorpay-api/) - India's leading payment gateway, UPI, cards, EMI, wallets

2. [Razorpay International Payments : Razorpay Forums | Product Hunt](https://www.producthunt.com/p/razorpay/razorpay-international-payments) - You can now accept international payments on Razorpay. Razorpay Payment Gateway and products like Su...

3. [Razorpay launches digital payment support for 100 currencies](https://www.business-standard.com/amp/article/news-ani/razorpay-launches-digital-payment-support-for-100-currencies-119060500789_1.html) - Razorpay, India's first converged payments solution company, today announced that it now supports 10...

4. [Accept International Payments for Global Business - Razorpay](https://razorpay.com/accept-international-payments/) - Accept international payments in 130+ currencies with Razorpay. Take cards, local bank transfers, an...

5. [Razorpay Payment Gateway Charges 2026: Pricing Breakdown](https://www.softwaresuggest.com/blog/razorpay-payment-gateway-charges/) - Discover Razorpay's fees and pricing for domestic and international transactions. Learn how to optim...

6. [Razorpay Payment Gateway Pricing and Fees Explained](https://razorpay.com/blog/razorpay-payment-gateway-pricing-explained/) - Razorpay Payment Gateway pricing explained. Understand domestic and international fees, UPI charges,...

7. [Best Subscription & Recurring Billing Platform in India - Free Demo](https://razorpay.com/subscriptions/) - Receive recurring payments. With Razorpay Subscriptions · Unlock growth with UPI AutoPay · Convert y...

8. [Razorpay payment gateway: Pricing, charges, and key points](https://wise.com/in/blog/razorpay-payment-gateway-pricing-charges-features) - Learn about Razorpay payment gateway and how much does it cost you. Find out about a smart way to ma...

9. [What Is a Recurring Transaction?: Meaning & How Do They Work?](https://razorpay.com/blog/recurring-transactions-meaning-how-they-work) - Businesses can enable recurring payments through platforms like Razorpay using payment methods such ...

10. [Master Recurring Payments with UPI 2.0 Autopay: 2026 Guide](https://razorpay.com/blog/master-recurring-payments-upi-autopay-guide/) - Razorpay UPI Autopay is built for merchants who want more than basic recurring payments – it is desi...

11. [Razorpay UPI Autopay for Recurring UPI Payments](https://razorpay.com/upi-autopay/) - Razorpay enables UPI Autopay instantly so your subscriptions can go live today. · Create plans, pric...

12. [Razorpay Review 2026: Features, Pricing, Limits for SaaS](https://dodopayments.com/blogs/razorpay-review)

13. [Razorpay partners with PayPal to help Indian MSME's go global](https://daijiworld.com/index.php/news/newsDisplay?newsID=777377) - Bengaluru, Dec 2 (IANS): Fintech unicorn Razorpay on Wednesday said it has partnership with global d...

14. [Razorpay AutoPay Revolutionizes Recurring Revenue Management](https://www.linkedin.com/posts/abhijith-b-39b156225_razorpay-autopay-upiautopay-activity-7424039967695323136-rYoJ) - We just rolled out Razorpay AutoPay end-to-end, and it materially changes how we handle recurring re...

