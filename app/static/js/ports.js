if (window.lucide) {
  window.lucide.createIcons();
}

const modal = document.getElementById('modal');
const modalContent = document.getElementById('modal-content');

const openPortDrawer = async (portId) => {
  if (!modal || !modalContent) return;
  const res = await fetch(`/ports/${portId}`);
  modalContent.innerHTML = await res.text();
  modal.classList.remove('hidden');
  modalContent.querySelector('[data-close-modal]')?.addEventListener('click', () => modal.classList.add('hidden'));
};

if (modal) {
  modal.addEventListener('click', (event) => {
    if (event.target === modal) {
      modal.classList.add('hidden');
    }
  });
}

const workspace = document.getElementById('ports-workspace');

if (workspace) {
  const portsRack = document.getElementById('ports-rack');
  const selectedLine = document.getElementById('ports-selected-line');
  const panel = document.getElementById('port-config-panel');
  const infoLine = document.getElementById('config-info');
  const form = document.getElementById('multi-port-form');
  const nativeVlanSelect = document.getElementById('vlan-native');
  const taggedVlanSelect = document.getElementById('tagged-vlans');
  const taggedRow = document.getElementById('custom-tagged-row');
  const manualFields = document.getElementById('manual-fields');
  const cancelBtn = document.getElementById('cancel-changes');
  const selectAllBtn = workspace.querySelector('[data-action="select-all"]');
  const deselectAllBtn = workspace.querySelector('[data-action="deselect-all"]');
  const detailBody = document.getElementById('ports-detail-body');
  const filterInputs = [...workspace.querySelectorAll('#ports-filters input[type="checkbox"]')];

  const state = {
    ports: JSON.parse(workspace.dataset.ports || '[]'),
    vlans: JSON.parse(workspace.dataset.vlans || '[]'),
    selected: new Set(),
    anchor: null,
    draft: null,
  };

  const vlanLabel = (id) => {
    const vlan = state.vlans.find((entry) => entry.id === id);
    return vlan ? `${vlan.name} (${vlan.id})` : `VLAN-${id} (${id})`;
  };

  const speedLabel = (port) => {
    if (port.portNumber > 48) return '10 GbE';
    const speed = String(port.speed || '').toLowerCase();
    if (speed.includes('10')) return '10 GbE';
    if (speed.includes('2.5')) return '2.5 GbE';
    if (speed.includes('100m') || speed === 'fe') return 'FE';
    return 'GbE';
  };

  const portClass = (port) => {
    if (port.portNumber > 48) return 'sfp';
    if (speedLabel(port) === '10 GbE') return 'ten-gbe';
    if (port.status === 'disabled') return 'disabled';
    if (port.status === 'restricted') return 'warning';
    if (port.linkState !== 'up') return 'disconnected';
    return 'active';
  };

  const shouldIncludePort = (port) => {
    const activeFilters = filterInputs.filter((input) => input.checked).map((input) => input.dataset.filter);
    if (!activeFilters.length || activeFilters.includes('all')) return true;

    const rules = {
      in_use: port.linkState === 'up',
      available: !port.connectedDevice,
      no_poe: port.poeMode === 'off',
      poe_plus: port.poeMode === 'poe_plus',
      fe: speedLabel(port) === 'FE',
      gbe: speedLabel(port) === 'GbE',
      '2_5gbe': speedLabel(port) === '2.5 GbE',
      '10gbe': speedLabel(port) === '10 GbE',
      sfp_plus: port.portNumber > 48,
    };

    return activeFilters.some((key) => rules[key]);
  };

  const renderVlanOptions = () => {
    const vlanEntries = state.vlans.length ? state.vlans : [{ id: 1, name: 'LAN-Default' }];
    const options = vlanEntries
      .map((vlan) => `<option value="${vlan.id}">${vlan.name} (${vlan.id})</option>`)
      .join('');
    nativeVlanSelect.innerHTML = options;
    taggedVlanSelect.innerHTML = options;
  };

  const sortedSelectedNumbers = () => state.ports
    .filter((port) => state.selected.has(port.id))
    .map((port) => port.portNumber)
    .sort((a, b) => a - b);

  const renderSelectionLine = () => {
    const numbers = sortedSelectedNumbers();
    selectedLine.textContent = numbers.length ? `Ports ${numbers.join(', ')}` : 'No ports selected';
  };

  const applyDraftToForm = () => {
    if (!state.draft) return;
    form.querySelector(`input[name="status"][value="${state.draft.status}"]`)?.click();
    nativeVlanSelect.value = String(state.draft.vlanNative);
    form.querySelector(`input[name="taggedPolicy"][value="${state.draft.taggedPolicy}"]`)?.click();
    [...taggedVlanSelect.options].forEach((option) => {
      option.selected = state.draft.vlanTagged.includes(Number(option.value));
    });
    form.querySelector(`input[name="poeMode"][value="${state.draft.poeMode}"]`)?.click();
    form.querySelector(`input[name="profile"][value="${state.draft.profile}"]`)?.click();
    form.speed.value = state.draft.speed || '1G';
    form.duplex.value = state.draft.duplex || 'full';

    taggedRow.hidden = state.draft.taggedPolicy !== 'custom';
    manualFields.hidden = state.draft.profile !== 'manual';
  };

  const updateDraftFromForm = () => {
    if (!state.draft) return;
    const formData = new FormData(form);
    state.draft.status = formData.get('status');
    state.draft.vlanNative = Number(formData.get('vlanNative'));
    state.draft.taggedPolicy = formData.get('taggedPolicy');
    state.draft.vlanTagged = [...taggedVlanSelect.selectedOptions].map((option) => Number(option.value));
    state.draft.poeMode = formData.get('poeMode');
    state.draft.profile = formData.get('profile');
    state.draft.speed = formData.get('speed');
    state.draft.duplex = formData.get('duplex');

    taggedRow.hidden = state.draft.taggedPolicy !== 'custom';
    manualFields.hidden = state.draft.profile !== 'manual';
  };

  const renderPanel = () => {
    const selectedPorts = state.ports.filter((port) => state.selected.has(port.id));
    if (!selectedPorts.length) {
      panel.hidden = true;
      state.draft = null;
      return;
    }

    if (!state.draft) {
      const [firstPort] = selectedPorts;
      state.draft = {
        status: firstPort.status,
        vlanNative: firstPort.vlanNative,
        taggedPolicy: firstPort.taggedPolicy || 'allow_all',
        vlanTagged: [...(firstPort.vlanTagged || [])],
        poeMode: firstPort.poeMode,
        profile: firstPort.profile || 'auto',
        speed: firstPort.speed || '1G',
        duplex: firstPort.duplex || 'full',
      };
    }

    panel.hidden = false;
    infoLine.textContent = `Displaying the configuration for port ${selectedPorts[0].portNumber} which will be applied to all selected ports.`;
    applyDraftToForm();
  };

  const renderPorts = () => {
    portsRack.innerHTML = state.ports
      .filter(shouldIncludePort)
      .map((port) => {
        const selected = state.selected.has(port.id) ? 'selected' : '';
        const statusClass = portClass(port);
        const poe = port.poeMode === 'poe_plus' ? '<i class="poe-icon" data-lucide="zap"></i>' : '';
        const device = port.connectedDevice ? '<i class="device-icon" data-lucide="plug"></i>' : '';
        return `<button type="button" class="port-tile ${statusClass} ${selected}" data-port-id="${port.id}" title="Port ${port.portNumber} | ${vlanLabel(port.vlanNative)}">${poe}${device}<span>${port.portNumber}</span></button>`;
      })
      .join('');

    if (window.lucide) {
      window.lucide.createIcons();
    }

    portsRack.querySelectorAll('.port-tile').forEach((button) => {
      button.addEventListener('click', (event) => {
        const portId = Number(button.dataset.portId);
        const index = state.ports.findIndex((port) => port.id === portId);
        if (index < 0) return;

        if (event.shiftKey && state.anchor !== null) {
          const anchorIndex = state.ports.findIndex((port) => port.id === state.anchor);
          const [start, end] = [Math.min(anchorIndex, index), Math.max(anchorIndex, index)];
          for (let i = start; i <= end; i += 1) {
            state.selected.add(state.ports[i].id);
          }
        } else if (event.ctrlKey || event.metaKey) {
          if (state.selected.has(portId)) {
            state.selected.delete(portId);
          } else {
            state.selected.add(portId);
          }
          state.anchor = portId;
        } else {
          if (state.selected.size === 1 && state.selected.has(portId)) {
            state.selected.delete(portId);
          } else {
            state.selected = new Set([portId]);
          }
          state.anchor = portId;
        }

        state.draft = null;
        renderPorts();
        renderSelectionLine();
        renderPanel();
      });

      button.addEventListener('dblclick', () => {
        const portId = Number(button.dataset.portId);
        openPortDrawer(portId);
      });
    });
  };

  const renderTable = () => {
    const rows = state.ports.filter(shouldIncludePort).map((port) => {
      const label = port.portNumber > 48 ? `SFP+${port.portNumber - 48}` : `Port-${port.portNumber}`;
      const connected = port.connectedDevice || '-';
      const profile = port.profile === 'manual' ? 'Manual' : 'Auto';
      const activityPct = Math.max(8, Math.min(95, parseFloat(port.txRate) || 8));
      return `<tr>
        <td>${port.portNumber}</td>
        <td>${label}</td>
        <td>🔒</td>
        <td>${port.poeMode === 'poe_plus' ? 'PoE+' : '-'}</td>
        <td>${speedLabel(port)}</td>
        <td>${connected}</td>
        <td>${profile}</td>
        <td><div class="activity-bar"><span style="width:${activityPct}%"></span></div></td>
        <td>${port.txRate === '0 Mbps' ? '0.0 GB' : port.txRate}</td>
        <td>${port.rxRate === '0 Mbps' ? '0.0 GB' : port.rxRate}</td>
        <td>${port.txRate}</td>
      </tr>`;
    }).join('');

    detailBody.innerHTML = rows || '<tr><td colspan="11" class="muted">No matching ports.</td></tr>';
  };

  form.addEventListener('change', updateDraftFromForm);

  cancelBtn.addEventListener('click', () => {
    state.draft = null;
    renderPanel();
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!state.selected.size || !state.draft) return;

    updateDraftFromForm();
    const payload = {
      portIds: [...state.selected],
      updates: state.draft,
    };

    const response = await fetch('/ports/bulk-update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      return;
    }

    const data = await response.json();
    const updated = new Map((data.ports || []).map((port) => [port.id, port]));
    state.ports = state.ports.map((port) => updated.get(port.id) || port);

    renderPorts();
    renderTable();
    renderSelectionLine();
    renderPanel();
  });

  selectAllBtn.addEventListener('click', () => {
    state.selected = new Set(state.ports.map((port) => port.id));
    state.draft = null;
    renderPorts();
    renderSelectionLine();
    renderPanel();
  });

  deselectAllBtn.addEventListener('click', () => {
    state.selected = new Set();
    state.draft = null;
    renderPorts();
    renderSelectionLine();
    renderPanel();
  });

  filterInputs.forEach((input) => {
    input.addEventListener('change', () => {
      if (input.dataset.filter === 'all' && input.checked) {
        filterInputs.forEach((entry) => {
          if (entry !== input) entry.checked = false;
        });
      }
      if (input.dataset.filter !== 'all' && input.checked) {
        const allInput = filterInputs.find((entry) => entry.dataset.filter === 'all');
        if (allInput) allInput.checked = false;
      }
      const allInput = filterInputs.find((entry) => entry.dataset.filter === 'all');
      const selectedSpecific = filterInputs.some((entry) => entry.dataset.filter !== 'all' && entry.checked);
      if (!selectedSpecific && allInput) allInput.checked = true;

      renderPorts();
      renderTable();
    });
  });

  renderVlanOptions();
  renderPorts();
  renderTable();
  renderSelectionLine();
  renderPanel();
}
