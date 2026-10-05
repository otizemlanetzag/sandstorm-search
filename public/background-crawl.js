(() => {
  const KEY = "sandstorm-background-crawl-disabled";
  const isDisabled = () => localStorage.getItem(KEY) === "1";

  const button = document.createElement("button");
  button.type = "button";
  button.textContent = isDisabled() ? "הפעל סריקה אצלי" : "הפסק סריקה אצלי";
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

  button.onclick = () => {
    if (isDisabled()) {
      localStorage.removeItem(KEY);
      button.textContent = "הפסק סריקה אצלי";
      start();
    } else {
      localStorage.setItem(KEY, "1");
      button.textContent = "הפעל סריקה אצלי";
      clearInterval(timer);
    }
  };

  document.body.appendChild(button);

  async function scanOnce() {
    if (isDisabled() || document.hidden) return;
    try {
      await fetch("/api/snake-crawl/background", {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin"
      });
    } catch (_) {}
  }

  let timer = null;
  function start() {
    clearInterval(timer);
    scanOnce();
    timer = setInterval(scanOnce, 30000);
  }

  start();
})();