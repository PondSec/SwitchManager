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

document.querySelectorAll('.frontpanel .port[data-port-id], .port-edit-btn[data-port-id]').forEach((button) => {
  button.addEventListener('click', (event) => {
    event.preventDefault();
    const portId = Number(button.dataset.portId);
    if (!Number.isFinite(portId)) return;
    openPortDrawer(portId);
  });
});

const workspace = document.getElementById('ports-workspace');

if (workspace) {
  const csrfToken = workspace.dataset.csrfToken || '';
  const portsRack = document.getElementById('ports-rack');
  const selectedLine = document.getElementById('ports-selected-line');
  const panel = document.getElementById('port-config-panel');
  const infoLine = document.getElementById('config-info');
  const feedback = document.getElementById('ports-feedback');
  const form = document.getElementById('multi-port-form');
  const applyButton = document.getElementById('apply-changes');
  const nativeVlanSelect = document.getElementById('vlan-native');
  const taggedVlanSelect = document.getElementById('tagged-vlans');
  const taggedRow = document.getElementById('custom-tagged-row');
  const manualFields = document.getElementById('manual-fields');
  const poeInputs = [...document.querySelectorAll('input[name="poeMode"]')];
  const cancelBtn = document.getElementById('cancel-changes');
  const selectAllBtn = workspace.querySelector('[data-action="select-all"]');
  const deselectAllBtn = workspace.querySelector('[data-action="deselect-all"]');
  const detailBody = document.getElementById('ports-detail-body');
  const filterInputs = [...workspace.querySelectorAll('#ports-filters input[type="checkbox"]')];
  const tabButtons = [...workspace.querySelectorAll('.ports-tab[data-view]')];
  const viewPanels = [...workspace.querySelectorAll('[data-view-panel]')];

  const state = {
    ports: JSON.parse(workspace.dataset.ports || '[]'),
    vlans: JSON.parse(workspace.dataset.vlans || '[]'),
    selected: new Set(),
    anchor: null,
    draft: null,
    currentView: 'ports',
  };

  const vlanLabel = (id) => {
    const vlan = state.vlans.find((entry) => entry.id === id);
    return vlan ? `${vlan.name} (${vlan.id})` : `VLAN-${id} (${id})`;
  };

  const speedLabel = (port) => {
    if (port.portNumber > 48) return '10 GbE';
    const speed = String(port.speed || '').toLowerCase();
    if (speed.includes('10000') || speed.includes('10gb') || speed === '10g') return '10 GbE';
    if (speed.includes('2500') || speed.includes('2.5g')) return '2.5 GbE';
    if (speed.includes('1000') || speed.includes('1g') || speed.includes('1000m')) return 'GbE';
    if ((speed.includes('100m') && !speed.includes('1000m')) || speed === 'fe') return 'FE';
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
    selectedLine.textContent = numbers.length ? `Ausgewählt: Port ${numbers.join(', ')}` : 'Keine Ports ausgewählt';
  };

  const setFeedback = (message, tone = 'info') => {
    if (!feedback) return;
    feedback.hidden = !message;
    feedback.textContent = message || '';
    feedback.dataset.tone = tone;
  };

  const activateView = (viewName) => {
    state.currentView = viewName;
    tabButtons.forEach((button) => {
      const active = button.dataset.view === viewName;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    viewPanels.forEach((panelEl) => {
      panelEl.hidden = panelEl.dataset.viewPanel !== viewName;
    });
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

    const allPoeSupported = selectedPorts.every((port) => port.poeSupported !== false);
    poeInputs.forEach((input) => {
      input.disabled = !allPoeSupported;
    });

    panel.hidden = false;
    infoLine.textContent = `Die gezeigte Konfiguration basiert auf Port ${selectedPorts[0].portNumber} und wird auf alle ausgewählten Ports angewendet.${allPoeSupported ? '' : ' PoE ist fuer die aktuelle Auswahl nicht verfuegbar.'}`;
    applyDraftToForm();
  };

  const renderPorts = () => {
    portsRack.innerHTML = state.ports
      .filter(shouldIncludePort)
      .map((port) => {
        const selected = state.selected.has(port.id) ? 'selected' : '';
        const statusClass = portClass(port);
        const poe = port.poeMode === 'poe_plus' ? '<i class="poe-icon" data-lucide="zap"></i>' : '';
        const device = (port.connectedDevice || port.clientCount) ? '<i class="device-icon" data-lucide="plug"></i>' : '';
        return `<button type="button" class="port-tile ${statusClass} ${selected}" data-port-id="${port.id}" title="Port ${port.portNumber} | ${port.vlanLabel || vlanLabel(port.vlanNative)}">${poe}${device}<span>${port.portNumber}</span></button>`;
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
      const defaultLabel = port.portNumber > 48 ? `SFP+${port.portNumber - 48}` : `Port ${port.portNumber}`;
      const label = port.alias || defaultLabel;
      const connected = port.connectedDevice || '-';
      const activityPct = Math.max(6, Math.min(100, Number(port.activityPercent) || 0));
      const status = port.status === 'disabled' ? 'Disabled' : (port.linkState === 'up' ? 'Up' : 'Down');
      const poeLabel = port.poeRole === 'input'
        ? 'PoE In'
        : port.poeRole === 'output'
          ? (port.poeMode === 'poe_plus' ? 'PoE Out On' : 'PoE Out')
          : '-';
      return `<tr>
        <td>${port.portNumber}</td>
        <td>${label}</td>
        <td>${status}</td>
        <td title="${port.poeNote || port.poeReason || ''}">${poeLabel}</td>
        <td>${speedLabel(port)}</td>
        <td>${port.vlanLabel || vlanLabel(port.vlanNative)}</td>
        <td>${connected}</td>
        <td>${port.clientCount || 0}</td>
        <td><div class="activity-bar"><span style="width:${activityPct}%"></span></div></td>
        <td>${port.txRate || '0 B'}</td>
        <td>${port.rxRate || '0 B'}</td>
        <td>${port.trafficHuman || '0 B'}</td>
      </tr>`;
    }).join('');

    detailBody.innerHTML = rows || '<tr><td colspan="12" class="muted">Keine Ports passend zum aktuellen Filter.</td></tr>';
  };

  form.addEventListener('change', updateDraftFromForm);

  cancelBtn.addEventListener('click', () => {
    state.draft = null;
    renderPanel();
    setFeedback('');
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!state.selected.size || !state.draft) return;

    updateDraftFromForm();
    const selectedPorts = sortedSelectedNumbers();
    const payload = {
      portIds: [...state.selected],
      updates: state.draft,
    };

    if (applyButton) {
      applyButton.disabled = true;
      applyButton.textContent = 'Wird angewendet...';
    }
    setFeedback(`Änderungen für Port ${selectedPorts.join(', ')} werden angewendet...`, 'info');

    try {
      const response = await fetch('/ports/bulk-update', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorPayload = await response.json().catch(() => ({}));
        const message = errorPayload.error || 'Port-Update fehlgeschlagen.';
        setFeedback(message, 'error');
        window.alert(message);
        return;
      }

      const data = await response.json();
      const updated = new Map((data.ports || []).map((port) => [port.id, port]));
      state.ports = state.ports.map((port) => updated.get(port.id) || port);

      renderPorts();
      renderTable();
      renderSelectionLine();
      renderPanel();
      setFeedback(`Port ${selectedPorts.join(', ')} aktualisiert. Wenn ein aktivierter Port ohne Kabel bleibt, erscheint er weiter als Down statt Disabled.`, 'success');
    } finally {
      if (applyButton) {
        applyButton.disabled = false;
        applyButton.textContent = 'Änderungen anwenden';
      }
    }
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

  tabButtons.forEach((button) => {
    button.addEventListener('click', () => {
      activateView(button.dataset.view || 'ports');
    });
  });

  renderVlanOptions();
  activateView('ports');
  renderPorts();
  renderTable();
  renderSelectionLine();
  renderPanel();
}
