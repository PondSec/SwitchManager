const modal = document.getElementById('modal');
const modalContent = document.getElementById('modal-content');

const openPortDrawer = async (portId) => {
  if (!modal || !modalContent) return;
  const res = await fetch(`/ports/${portId}`);
  modalContent.innerHTML = await res.text();
  modal.classList.remove('hidden');
  modalContent.querySelector('[data-close-modal]')?.addEventListener('click', () => modal.classList.add('hidden'));
};

document.querySelectorAll('.port, .port-edit-btn').forEach((button) => {
  button.addEventListener('click', () => {
    const id = button.dataset.portId;
    if (id) openPortDrawer(id);
  });
});

if (modal) {
  modal.addEventListener('click', (event) => {
    if (event.target === modal) {
      modal.classList.add('hidden');
    }
  });
}

const portTableWrapper = document.getElementById('port-table-wrapper');
if (portTableWrapper) {
  setInterval(async () => {
    const res = await fetch('/ports/refresh');
    if (res.ok) {
      portTableWrapper.innerHTML = await res.text();
    }
  }, 15000);
}
