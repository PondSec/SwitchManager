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
    document.querySelectorAll('.tab-content').forEach((el) => el.classList.remove('active'));
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
