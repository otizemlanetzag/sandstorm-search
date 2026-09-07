(() => {
  const KEY = 'sandstorm.safesearch';
  const checkbox = document.getElementById('safeSearch');
  const status = document.getElementById('status');

  // SafeSearch defaults to ON. Only an explicit saved 'off' disables it.
  checkbox.checked = localStorage.getItem(KEY) !== 'off';

  checkbox.addEventListener('change', () => {
    localStorage.setItem(KEY, checkbox.checked ? 'on' : 'off');
    status.textContent = checkbox.checked
      ? 'SafeSearch is enabled. Adult-content indicators will be filtered from search results.'
      : 'SafeSearch is disabled. Search results will not receive the SafeSearch filter.';
  });
})();
