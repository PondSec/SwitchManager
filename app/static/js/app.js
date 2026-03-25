document.querySelectorAll('form[data-confirm]').forEach((form) => {
  form.addEventListener('submit', (e) => {
    const msg = form.dataset.confirm || 'Aktion bestätigen?';
    if (!window.confirm(msg)) e.preventDefault();
  });
});

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    const id = tab.dataset.tab;
    tab.parentElement.querySelectorAll('.tab').forEach((el) => el.classList.remove('active'));
    const scope = tab.closest('.card') || document;
    scope.querySelectorAll('.tab-content').forEach((el) => el.classList.remove('active'));
    tab.classList.add('active');
    const panel = document.getElementById(id);
    if (panel) panel.classList.add('active');
  });
});

const switcher = document.getElementById('device-switch');
if (switcher) {
  switcher.addEventListener('change', () => {
    window.location.href = `/devices/${switcher.value}/select`;
  });
}

const globalSearch = document.querySelector('.top-search');
if (globalSearch) {
  globalSearch.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      const q = encodeURIComponent(globalSearch.value.trim());
      window.location.href = `/devices/?q=${q}&status=all&sort=name&view=table`;
    }
  });
}
