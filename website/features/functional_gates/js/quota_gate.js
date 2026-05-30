/* ZKQuotaGate — single reusable popup for 402 quota_exhausted responses.
 *
 * Sits between the 4xx error and ZKPricing.openPurchase so the user sees a
 * lightweight intermediate modal ("Sorry! You have run out of Zettels …")
 * with two CTAs:
 *   1. Buy Zettel / Buy Kasten / Buy Question  — opens Razorpay via ZKPricing.
 *   2. Show ad                                  — disabled, "Coming soon…".
 *
 * Public API:
 *   window.ZKQuotaGate.show({
 *     detail:        the response detail (must include `code:'quota_exhausted', meter`),
 *     source:        free-form string for telemetry ('home:add-zettel' etc.),
 *     resumeAction:  opaque object handed to ZKPricing for post-purchase replay,
 *     onResume:      callback invoked after the buy flow completes.
 *   }) -> Promise<void> that resolves on close.
 *
 * Drop-in replacement for direct calls to window.ZKPricing.openPurchase(...).
 */
(function () {
  'use strict';

  var METER_LABELS = {
    zettel:       { singular: 'Zettel',   plural: 'Zettels'   },
    kasten:       { singular: 'Kasten',   plural: 'Kastens'   },
    rag_question: { singular: 'question', plural: 'questions' }
  };

  var ROOT_ID = 'zk-quota-gate-root';
  var _activeResolve = null;

  function ensureRoot() {
    var existing = document.getElementById(ROOT_ID);
    if (existing) return existing;
    var root = document.createElement('div');
    root.id = ROOT_ID;
    root.className = 'zk-quota-gate-backdrop';
    root.setAttribute('aria-hidden', 'true');
    root.innerHTML = [
      '<div class="zk-quota-gate-card" role="dialog" aria-modal="true" aria-labelledby="zk-quota-gate-title">',
      '  <button type="button" class="zk-quota-gate-close" aria-label="Close">&times;</button>',
      '  <h2 id="zk-quota-gate-title" class="zk-quota-gate-title"></h2>',
      '  <p class="zk-quota-gate-body"></p>',
      '  <div class="zk-quota-gate-actions">',
      '    <button type="button" class="zk-quota-gate-btn primary" data-action="buy">',
      '      <span class="zk-quota-gate-btn-label">Buy</span>',
      '      <span class="zk-quota-gate-btn-sub"></span>',
      '    </button>',
      '    <button type="button" class="zk-quota-gate-btn secondary" data-action="ad" disabled>',
      '      <span class="zk-quota-gate-btn-label">Show ad</span>',
      '      <span class="zk-quota-gate-btn-sub">Coming soon…</span>',
      '    </button>',
      '  </div>',
      '</div>'
    ].join('');
    document.body.appendChild(root);

    root.addEventListener('click', function (e) {
      if (e.target === root) closeWith('dismiss');
    });
    root.querySelector('.zk-quota-gate-close').addEventListener('click', function () {
      closeWith('dismiss');
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && root.classList.contains('visible')) closeWith('dismiss');
    });
    return root;
  }

  function priceHintFromDetail(detail) {
    // Detail.recommended_products is an array of product_ids; we don't have
    // catalog prices in this script. Surface a stable per-unit hint inferred
    // from product_id by parsing the trailing pack size — e.g. `zettel_1`
    // -> "₹15 / Zettel" (using launch pricing per docs/research/pricing1.md).
    // If unavailable, render an empty hint.
    var meter = detail && detail.meter;
    var recs = (detail && detail.recommended_products) || [];
    var unit = METER_LABELS[meter] ? METER_LABELS[meter].singular.toLowerCase() : meter || 'unit';
    if (!recs.length) return '';
    // Heuristic display only — the real price comes from the Razorpay
    // checkout that ZKPricing.openPurchase launches.
    var hints = {
      zettel: '₹15 / zettel',
      kasten: '₹69 / kasten',
      rag_question: '₹79 / 100 questions'
    };
    return hints[meter] || ('Buy ' + unit + ' packs');
  }

  function copyForMeter(meter) {
    var label = METER_LABELS[meter] || { plural: meter || 'units', singular: meter || 'unit' };
    return {
      title: 'Sorry — you have run out of ' + label.plural,
      body: 'You have reached your current limit. Pick how to continue:',
      buyLabel: 'Buy ' + label.singular
    };
  }

  function paint(root, detail) {
    var copy = copyForMeter(detail && detail.meter);
    root.querySelector('.zk-quota-gate-title').textContent = copy.title;
    root.querySelector('.zk-quota-gate-body').textContent = copy.body;
    var buyBtn = root.querySelector('.zk-quota-gate-btn.primary');
    buyBtn.querySelector('.zk-quota-gate-btn-label').textContent = copy.buyLabel;
    buyBtn.querySelector('.zk-quota-gate-btn-sub').textContent = priceHintFromDetail(detail);
  }

  function closeWith(reason) {
    var root = document.getElementById(ROOT_ID);
    if (!root) return;
    root.classList.remove('visible');
    root.setAttribute('aria-hidden', 'true');
    if (typeof _activeResolve === 'function') {
      var r = _activeResolve;
      _activeResolve = null;
      r(reason);
    }
  }

  function show(opts) {
    opts = opts || {};
    var detail = opts.detail || {};
    var root = ensureRoot();
    paint(root, detail);

    var buyBtn = root.querySelector('.zk-quota-gate-btn.primary');
    var newBuyBtn = buyBtn.cloneNode(true);
    buyBtn.parentNode.replaceChild(newBuyBtn, buyBtn);
    newBuyBtn.addEventListener('click', function () {
      if (window.ZKPricing && typeof window.ZKPricing.openPurchase === 'function') {
        var launch = window.ZKPricing.openPurchase({
          detail: detail,
          source: opts.source,
          resumeAction: opts.resumeAction,
          onResume: opts.onResume
        });
        if (launch && typeof launch.then === 'function') {
          launch.finally(function () { closeWith('buy'); });
        } else {
          closeWith('buy');
        }
      } else {
        // Fall back to /pricing — ZKPricing not loaded on this page.
        var qp = detail.meter ? ('?resource=' + encodeURIComponent(detail.meter) + '&origin=gate') : '';
        window.location.href = '/pricing' + qp;
        closeWith('buy');
      }
    });

    root.classList.add('visible');
    root.setAttribute('aria-hidden', 'false');
    return new Promise(function (resolve) {
      _activeResolve = resolve;
    });
  }

  // Single shared recognizer for the quota_exhausted condition across every
  // shape the error can arrive in. EXACT equality only (never substring) so a
  // future `quota_*` sibling (e.g. a soft-limit warning) cannot false-match.
  // Always returns the canonical underscore dict {code:'quota_exhausted',
  // meter, ...} or null.
  // NOTE: tolerates two wire spellings of the quota code (top-level
  // 'quota-exhausted' slug + nested detail.code 'quota_exhausted') during the
  // quota-code canonicalization migration. Remove the slug arms after the
  // server canonicalization PR ships and its deprecation window closes
  // (tracking: server wire-format canonicalization follow-up, spec §8).
  function _asQuota(meter, recs) {
    return { code: 'quota_exhausted', meter: meter, recommended_products: recs };
  }
  function extractQuotaDetail(x) {
    if (!x || typeof x !== 'object') return null;
    // 1. direct canonical dict
    if (x.code === 'quota_exhausted' && x.meter) return x;
    // 2. error/body whose .detail is the canonical dict (sync + normalized async)
    var d = x.detail;
    if (d && typeof d === 'object' && d.code === 'quota_exhausted' && d.meter) return d;
    // 3. raw failed-op body: { error: <problem> }
    var p = (x.error && typeof x.error === 'object') ? x.error : null;
    if (p) {
      if (p.detail && typeof p.detail === 'object'
          && p.detail.code === 'quota_exhausted' && p.detail.meter) return p.detail;
      if (p.code === 'quota-exhausted' && p.detail && p.detail.meter) {
        return _asQuota(p.detail.meter, p.detail.recommended_products);
      }
    }
    // 4. hyphen-slug at this level with nested meter
    if (x.code === 'quota-exhausted' && d && typeof d === 'object' && d.meter) {
      return _asQuota(d.meter, d.recommended_products);
    }
    return null;
  }

  function isQuotaDetail(detail) {
    return !!(detail && detail.code === 'quota_exhausted' && detail.meter);
  }

  window.ZKQuotaGate = {
    show: show,
    close: function () { closeWith('programmatic'); },
    isQuotaDetail: isQuotaDetail,
    extractQuotaDetail: extractQuotaDetail
  };
})();
