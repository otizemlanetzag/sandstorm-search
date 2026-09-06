(() => {
  const RULES = window.SANDSTORM_ADBLOCK_RULES || { blocked_host_patterns: [], blocked_url_patterns: [] };
  const hosts = RULES.blocked_host_patterns.map(x => String(x).toLowerCase());
  const urls = RULES.blocked_url_patterns.map(x => String(x).toLowerCase());

  function shouldBlock(value) {
    try {
      const u = new URL(value, location.href);
      const host = u.hostname.toLowerCase();
      const path = (u.pathname + u.search).toLowerCase();
      return hosts.some(pattern => host === pattern || host.endsWith('.' + pattern)) ||
             urls.some(pattern => path.includes(pattern));
    } catch (_) {
      return false;
    }
  }

  function removeAds(root = document) {
    const selectors = [
      '[id*="ad-" i]', '[id*="ads-" i]', '[id*="advert" i]',
      '[class*="ad-" i]', '[class*="ads-" i]', '[class*="advert" i]',
      '[class*="sponsor" i]', '[aria-label*="advert" i]',
      'iframe[src]', 'script[src]'
    ];
    for (const el of root.querySelectorAll(selectors.join(','))) {
      if (el.matches('iframe[src],script[src]') && !shouldBlock(el.src)) continue;
      if (el !== document.body && el !== document.documentElement) el.remove();
    }
  }

  // Remove known ad/tracker network elements before they can execute when possible.
  const originalFetch = window.fetch;
  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : input && input.url;
    if (url && shouldBlock(url)) return Promise.reject(new DOMException('Blocked by Sandstorm Ad Blocker', 'AbortError'));
    return originalFetch.call(this, input, init);
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    if (url && shouldBlock(String(url))) {
      this.__sandstormBlocked = true;
      return;
    }
    return originalOpen.call(this, method, url, ...rest);
  };

  const observer = new MutationObserver(mutations => {
    for (const mutation of mutations) for (const node of mutation.addedNodes) {
      if (node.nodeType === Node.ELEMENT_NODE) removeAds(node);
    }
  });

  function start() {
    removeAds();
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();

  window.SandstormAdBlock = Object.freeze({ enabled: true, shouldBlock });
})();
