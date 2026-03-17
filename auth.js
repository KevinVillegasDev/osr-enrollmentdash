/**
 * EasyPay Finance — Client-side password gate
 *
 * Two tiers:
 *   1. Site-wide: all pages require the team password
 *   2. Analytics-only: analytics.html requires an additional password (Kevin only)
 *
 * Passwords are stored as SHA-256 hashes. Auth state persists via localStorage.
 */
(function () {
  'use strict';

  // SHA-256 hashes (never store plaintext)
  var SITE_HASH = '380a1bfdb04042bd9997f5f9c3f3d7452fec2bb9258e94cd9cbf3bd0ce720bbb';
  var ANALYTICS_HASH = '129589a884d88f3dc379505bb51509b9728ca8a634e068bbaebf6b58dc894b80';

  var LS_SITE_KEY = 'epf_site_auth';
  var LS_ANALYTICS_KEY = 'epf_analytics_auth';

  var isAnalyticsPage = /analytics\.html/i.test(window.location.pathname);

  // ── Helpers ──────────────────────────────────────────────────────────
  async function sha256(str) {
    var buf = new TextEncoder().encode(str);
    var hash = await crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(hash)).map(function (b) {
      return b.toString(16).padStart(2, '0');
    }).join('');
  }

  function hidePageContent() {
    document.documentElement.style.visibility = 'hidden';
    document.documentElement.style.overflow = 'hidden';
  }

  function showPageContent() {
    document.documentElement.style.visibility = '';
    document.documentElement.style.overflow = '';
  }

  // ── Overlay UI ──────────────────────────────────────────────────────
  function createOverlay(title, subtitle, onSubmit) {
    var overlay = document.createElement('div');
    overlay.id = 'epf-auth-overlay';
    overlay.style.cssText = [
      'position:fixed', 'inset:0', 'z-index:999999',
      'background:#0D1321', 'display:flex', 'align-items:center',
      'justify-content:center', 'font-family:"DM Sans","Segoe UI",system-ui,sans-serif'
    ].join(';');

    var card = document.createElement('div');
    card.style.cssText = [
      'background:#151E2F', 'border:1px solid #293852', 'border-radius:16px',
      'padding:40px', 'width:380px', 'max-width:90vw', 'text-align:center',
      'box-shadow:0 25px 50px rgba(0,0,0,0.5)'
    ].join(';');

    // Logo / icon
    var icon = document.createElement('div');
    icon.style.cssText = [
      'width:56px', 'height:56px', 'margin:0 auto 20px',
      'background:linear-gradient(135deg,#5B9BFF,#818CF8)',
      'border-radius:14px', 'display:flex', 'align-items:center',
      'justify-content:center', 'font-size:24px'
    ].join(';');
    icon.textContent = '\uD83D\uDD12';

    var h2 = document.createElement('h2');
    h2.style.cssText = 'color:#F1F5F9;font-size:22px;font-weight:700;margin-bottom:6px;letter-spacing:-0.02em';
    h2.textContent = title;

    var sub = document.createElement('p');
    sub.style.cssText = 'color:#8494AB;font-size:14px;margin-bottom:24px';
    sub.textContent = subtitle;

    var input = document.createElement('input');
    input.type = 'password';
    input.placeholder = 'Enter password';
    input.autocomplete = 'off';
    input.style.cssText = [
      'width:100%', 'padding:12px 16px', 'border-radius:10px',
      'border:1px solid #293852', 'background:#0D1321', 'color:#F1F5F9',
      'font-size:15px', 'font-family:inherit', 'outline:none',
      'margin-bottom:12px', 'transition:border-color 0.2s'
    ].join(';');
    input.addEventListener('focus', function () { input.style.borderColor = '#5B9BFF'; });
    input.addEventListener('blur', function () { input.style.borderColor = '#293852'; });

    var errMsg = document.createElement('p');
    errMsg.style.cssText = 'color:#F87171;font-size:13px;margin-bottom:12px;min-height:18px';
    errMsg.textContent = '';

    var btn = document.createElement('button');
    btn.textContent = 'Unlock';
    btn.style.cssText = [
      'width:100%', 'padding:12px', 'border:none', 'border-radius:10px',
      'background:linear-gradient(135deg,#5B9BFF,#818CF8)', 'color:#fff',
      'font-size:15px', 'font-weight:600', 'font-family:inherit',
      'cursor:pointer', 'transition:opacity 0.2s'
    ].join(';');
    btn.addEventListener('mouseenter', function () { btn.style.opacity = '0.9'; });
    btn.addEventListener('mouseleave', function () { btn.style.opacity = '1'; });

    async function submit() {
      var val = input.value.trim();
      if (!val) { errMsg.textContent = 'Please enter a password.'; return; }
      var ok = await onSubmit(val);
      if (!ok) {
        errMsg.textContent = 'Incorrect password. Try again.';
        input.value = '';
        input.focus();
      }
    }

    btn.addEventListener('click', submit);
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') submit(); });

    card.appendChild(icon);
    card.appendChild(h2);
    card.appendChild(sub);
    card.appendChild(input);
    card.appendChild(errMsg);
    card.appendChild(btn);
    overlay.appendChild(card);

    document.body.appendChild(overlay);
    input.focus();
    return overlay;
  }

  function removeOverlay() {
    var el = document.getElementById('epf-auth-overlay');
    if (el) el.remove();
    showPageContent();
  }

  // ── Auth Flow ────────────────────────────────────────────────────────
  async function checkAuth() {
    // 1. Site-wide gate
    var storedSite = localStorage.getItem(LS_SITE_KEY);
    if (storedSite !== SITE_HASH) {
      hidePageContent();
      createOverlay(
        'EasyPay Dashboard',
        'Enter the team password to continue.',
        async function (val) {
          var hash = await sha256(val);
          if (hash === SITE_HASH) {
            localStorage.setItem(LS_SITE_KEY, hash);
            removeOverlay();
            // After site auth, check analytics gate
            if (isAnalyticsPage) await checkAnalyticsAuth();
            return true;
          }
          return false;
        }
      );
      return;
    }

    // 2. Analytics-only gate (if on analytics page)
    if (isAnalyticsPage) {
      await checkAnalyticsAuth();
    }
  }

  async function checkAnalyticsAuth() {
    var storedAnalytics = localStorage.getItem(LS_ANALYTICS_KEY);
    if (storedAnalytics === ANALYTICS_HASH) return; // already authed

    hidePageContent();
    createOverlay(
      'Analytics Access',
      'This page requires an additional password.',
      async function (val) {
        var hash = await sha256(val);
        if (hash === ANALYTICS_HASH) {
          localStorage.setItem(LS_ANALYTICS_KEY, hash);
          removeOverlay();
          return true;
        }
        return false;
      }
    );
  }

  // ── Init ──────────────────────────────────────────────────────────────
  // Hide content immediately to prevent flash of protected content
  hidePageContent();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { checkAuth(); });
  } else {
    checkAuth();
  }

  // If already authed, show content right away (no flash)
  var fastSite = localStorage.getItem(LS_SITE_KEY) === SITE_HASH;
  var fastAnalytics = !isAnalyticsPage || localStorage.getItem(LS_ANALYTICS_KEY) === ANALYTICS_HASH;
  if (fastSite && fastAnalytics) {
    showPageContent();
  }
})();
