(function () {
  'use strict';

  function hasQuotaDetail(detail) {
    return Boolean(detail && detail.code === 'quota_exhausted' && detail.meter);
  }

  function authToken() {
    if (typeof window.getAuthToken === 'function') return window.getAuthToken();
    try {
      var raw = window.localStorage && window.localStorage.getItem('zk-auth-token');
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      return parsed && parsed.access_token ? parsed.access_token : null;
    } catch (_) {
      return null;
    }
  }

  function authHeaders() {
    var token = authToken();
    return token ? { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
  }

  async function fetchJson(path, options) {
    options = options || {};
    options.headers = Object.assign({}, options.headers || {});
    var response = await fetch(path, options);
    var payload = null;
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) {
      var detail = payload && payload.detail ? payload.detail : payload;
      var err = new Error((detail && detail.message) || 'Request failed');
      err.status = response.status;
      err.detail = detail;
      throw err;
    }
    return payload;
  }

  function findCatalogProduct(catalog, productId) {
    var plans = catalog && catalog.plans ? catalog.plans : {};
    for (var planId in plans) {
      var periods = plans[planId].periods || {};
      for (var periodId in periods) {
        if (periods[periodId].id === productId) return { kind: 'subscription', amount: periods[periodId].amount, product: periods[periodId] };
      }
    }
    var packs = catalog && catalog.packs ? catalog.packs : {};
    for (var group in packs) {
      for (var i = 0; i < packs[group].length; i++) {
        if (packs[group][i].id === productId) return { kind: 'pack', amount: packs[group][i].amount, product: packs[group][i] };
      }
    }
    return null;
  }

  async function ensureBillingProfile() {
    var token = authToken();
    if (!token) {
      window.location.href = '/?auth=login&return=' + encodeURIComponent(window.location.pathname + window.location.search);
      throw new Error('Please sign in to continue checkout.');
    }

    var profilePayload = await fetchJson('/api/pricing/billing-profile', { headers: authHeaders() });
    var profile = profilePayload && profilePayload.profile;
    if (profile && profile.phone) return profile;

    var phone = window.prompt('Enter your phone number for secure checkout');
    if (!phone) throw new Error('Phone number is required for checkout.');
    return await fetchJson('/api/pricing/billing-profile', {
      method: 'PUT',
      headers: authHeaders(),
      body: JSON.stringify({ phone: phone })
    });
  }

  function chooseProductId(options, catalog) {
    if (options.productId) return options.productId;
    var detail = options.detail || {};
    var recommended = options.recommendedProducts || detail.recommended_products || [];
    return recommended[0] || null;
  }

  async function createCheckout(options, productId, productInfo) {
    var endpoint = productInfo.kind === 'subscription' ? '/api/payments/subscriptions' : '/api/payments/orders';
    var expectedAmount = Number.isFinite(options.expectedAmount) ? options.expectedAmount : productInfo.amount;
    return await fetchJson(endpoint, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        product_id: productId,
        source: options.source || 'unknown',
        expected_amount: expectedAmount,
        resume_token: options.detail && options.detail.resume_token ? options.detail.resume_token : null
      })
    });
  }

  function showComingSoonNotice(options) {
    var message = 'You need more ' + ((options.detail && options.detail.meter) || options.meter || 'credits') + '. Buy credits to continue.';
    var usePack = window.confirm(message + '\n\nWatch an ad is coming soon and is disabled for now.\n\nContinue to checkout?');
    return usePack;
  }

  async function openPurchase(options) {
    options = options || {};
    var detail = options.detail || {};
    var resumeAction = options.resumeAction || detail.resumeAction || null;

    window.dispatchEvent(new CustomEvent('zk:pricing:open', {
      detail: {
        meter: options.meter || detail.meter,
        source: options.source || 'unknown',
        recommendedProducts: options.recommendedProducts || detail.recommended_products || [],
        resumeAction: resumeAction
      }
    }));

    window.ZKPricing.pendingResume = {
      resumeAction: resumeAction,
      onResume: typeof options.onResume === 'function' ? options.onResume : null
    };

    if (!showComingSoonNotice(options)) return;

    var catalog = await fetchJson('/api/pricing/catalog');
    var productId = chooseProductId(options, catalog);
    if (!productId) {
      window.location.href = '/pricing';
      return;
    }
    var productInfo = findCatalogProduct(catalog, productId);
    if (!productInfo && /^custom_(zettel|kasten|question)_\d+$/.test(productId) && Number.isFinite(options.expectedAmount)) {
      productInfo = { kind: 'pack', amount: options.expectedAmount };
    }
    if (!productInfo) throw new Error('Selected product is no longer available.');
    if (Number.isFinite(options.expectedAmount) && options.expectedAmount !== productInfo.amount) {
      throw new Error('Displayed price changed. Refresh pricing before checkout.');
    }

    await ensureBillingProfile();
    await createCheckout(options, productId, productInfo);
    await resumePendingPurchase();
  }

  async function resumePendingPurchase() {
    var pending = window.ZKPricing && window.ZKPricing.pendingResume;
    if (pending && typeof pending.onResume === 'function') {
      await pending.onResume(pending.resumeAction);
      window.ZKPricing.pendingResume = null;
    }
  }

  window.ZKPricing = window.ZKPricing || {};
  window.ZKPricing.fetchJson = fetchJson;
  window.ZKPricing.hasQuotaDetail = hasQuotaDetail;
  window.ZKPricing.openPurchase = openPurchase;
  window.ZKPricing.resumePendingPurchase = resumePendingPurchase;
})();
