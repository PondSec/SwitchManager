const modal = document.getElementById('modal');
const modalContent = document.getElementById('modal-content');

document.querySelectorAll('.port').forEach((button) => {
  button.addEventListener('click', async () => {
    const id = button.dataset.portId;
    const res = await fetch(`/ports/${id}`);
    modalContent.innerHTML = await res.text();
    modal.classList.remove('hidden');
    modalContent.querySelector('[data-close-modal]')?.addEventListener('click', () => modal.classList.add('hidden'));
  });
});

setInterval(async () => {
  const wrapper = document.getElementById('port-table-wrapper');
  if (!wrapper) return;
  const res = await fetch('/ports/refresh');
  wrapper.innerHTML = await res.text();
}, 15000);
