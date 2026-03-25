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

const toggleButtons = document.querySelectorAll('[data-toggle]');
const closeAllMenus = () => {
  document.querySelectorAll('.dropdown, .tray').forEach((el) => el.classList.remove('open'));
  document.querySelectorAll('[data-toggle]').forEach((btn) => btn.classList.remove('open'));
};

toggleButtons.forEach((button) => {
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    const targetId = button.dataset.toggle;
    const panel = document.getElementById(targetId);
    if (!panel) return;

    const isOpen = panel.classList.contains('open');
    closeAllMenus();
    if (!isOpen) {
      panel.classList.add('open');
      button.classList.add('open');
    }
  });
});

document.addEventListener('click', () => closeAllMenus());
document.querySelectorAll('.dropdown, .tray').forEach((panel) => panel.addEventListener('click', (event) => event.stopPropagation()));

const globalSearch = document.getElementById('global-search');
if (globalSearch) {
  globalSearch.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      const q = encodeURIComponent(globalSearch.value.trim());
      window.location.href = `/devices/?q=${q}&status=all&sort=name&view=table`;
    }
  });
}
