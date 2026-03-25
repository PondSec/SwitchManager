document.querySelectorAll('form[data-confirm]').forEach((form) => {
  form.addEventListener('submit', (e) => {
    const msg = form.dataset.confirm || 'Aktion bestätigen?';
    if (!window.confirm(msg)) e.preventDefault();
  });
});

document.querySelectorAll('form[data-busy-submit]').forEach((form) => {
  form.addEventListener('submit', () => {
    const submitButton = form.querySelector('button[type="submit"]');
    if (!submitButton) return;
    submitButton.disabled = true;
    submitButton.dataset.originalLabel = submitButton.textContent || '';
    submitButton.textContent = form.dataset.busyLabel || 'Wird gespeichert...';
    form.classList.add('is-submitting');
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

document.querySelectorAll('[data-table-filter]').forEach((input) => {
  const tableName = input.dataset.tableFilter;
  const bodies = [...document.querySelectorAll(`[data-filter-body="${tableName}"]`)];
  const empties = [...document.querySelectorAll(`[data-filter-empty="${tableName}"]`)];
  if (!bodies.length) return;

  const updateFilter = () => {
    const query = input.value.trim().toLowerCase();
    let totalVisible = 0;

    bodies.forEach((body) => {
      let visible = 0;
      body.querySelectorAll('[data-filter-row]').forEach((row) => {
        const text = (row.dataset.filterText || row.textContent || '').toLowerCase();
        const show = !query || text.includes(query);
        row.hidden = !show;
        if (show) visible += 1;
      });
      totalVisible += visible;
    });

    empties.forEach((row) => {
      row.hidden = totalVisible !== 0;
    });
  };

  input.addEventListener('input', updateFilter);
  updateFilter();
});
