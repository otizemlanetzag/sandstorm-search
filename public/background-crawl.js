(() => {
  const button = document.createElement("button");
  button.type = "button";
  Object.assign(button.style, {
    position: "fixed",
    left: "12px",
    bottom: "12px",
    zIndex: "2147483647",
    padding: "7px 10px",
    border: "1px solid #c2a67d",
    borderRadius: "8px",
    background: "#efeae0",
    color: "#3e2723",
    font: "12px system-ui,sans-serif",
    cursor: "pointer",
    opacity: "0.9"
  });
  document.body.appendChild(button);

  let enabled = true;
  let timer = null;
  let accountSettings = null;

  async function loadAccountSetting() {
    try {
      const response = await fetch("/api/account/me", {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin"
      });
      if (!response.ok) return;
      const data = await response.json();
      if (!data.logged_in) {
        button.textContent = "הפסק סריקה אצלי";
        enabled = true;
        start();
        return;
      }
      accountSettings = data.settings && typeof data.settings === "object"
        ? data.settings
        : {};
      enabled = accountSettings.backgroundCrawl !== false;
      button.textContent = enabled ? "הפסק סריקה אצלי" : "הפעל סריקה אצלי";
      if (enabled) start();
    } catch (_) {
      button.textContent = "הפסק סריקה אצלי";
    }
  }

  async function saveSetting(value) {
    if (!accountSettings) {
      button.textContent = "יש להתחבר כדי לשמור את ההגדרה";
      setTimeout(() => {
        button.textContent = enabled ? "הפסק סריקה אצלי" : "הפעל סריקה אצלי";
      }, 2500);
      return false;
    }

    const settings = { ...accountSettings, backgroundCrawl: value };
    try {
      const response = await fetch("/api/account/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ settings })
      });
      if (!response.ok) return false;
      const data = await response.json();
      accountSettings = data.settings || settings;
      enabled = value;
      button.textContent = enabled ? "הפסק סריקה אצלי" : "הפעל סריקה אצלי";
      return true;
    } catch (_) {
      return false;
    }
  }

  button.onclick = async () => {
    button.disabled = true;
    const next = !enabled;
    const saved = await saveSetting(next);
    if (saved) {
      if (next) start();
      else stop();
    }
    button.disabled = false;
  };

  async function scanOnce() {
    if (!enabled || document.hidden) return;
    try {
      await fetch("/api/snake-crawl/background", {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin"
      });
    } catch (_) {}
  }

  function stop() {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  function start() {
    stop();
    scanOnce();
    timer = setInterval(scanOnce, 30000);
  }

  button.textContent = "הפסק סריקה אצלי";
  loadAccountSetting();
})();