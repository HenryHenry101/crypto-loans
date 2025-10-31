(function () {
  const connectWalletBtn = document.getElementById('connectWallet');
  const walletAddressEl = document.getElementById('walletAddress');
  const btcBalanceEl = document.getElementById('btcBalance');
  const btcbBalanceEl = document.getElementById('btcbBalance');
  const moneriumStatusEl = document.getElementById('moneriumStatus');
  const loanForm = document.getElementById('loanForm');
  const eurAmountInput = document.getElementById('eurAmount');
  const ltvSlider = document.getElementById('ltv');
  const ltvValue = document.getElementById('ltvValue');
  const btcRequiredInput = document.getElementById('btcRequired');
  const durationInput = document.getElementById('duration');
  const simulationOutput = document.getElementById('simulationOutput');
  const loansTableBody = document.querySelector('#loansTable tbody');
  const repayForm = document.getElementById('repayForm');
  const repayStatus = document.getElementById('repayStatus');
  const metricsEl = document.getElementById('platformMetrics');

  const API_BASE = (window.APP_CONFIG && window.APP_CONFIG.backendUrl) || 'http://localhost:8080';
  const API_KEY = (window.APP_CONFIG && window.APP_CONFIG.apiKey) || '';

  let account;
  let priceFeeds = {
    BTC_EUR: 35000,
  };

  async function apiFetch(path, options) {
    const opts = Object.assign({
      headers: {
        'Content-Type': 'application/json',
      },
    }, options || {});
    if (API_KEY) {
      opts.headers['X-API-Key'] = API_KEY;
    }
    const response = await fetch(`${API_BASE}${path}`, opts);
    if (!response.ok) {
      let message = `Error ${response.status}`;
      try {
        const data = await response.json();
        if (data.error) {
          message = `${message}: ${data.error}`;
        }
      } catch (err) {
        // ignore
      }
      throw new Error(message);
    }
    return response.json();
  }

  async function refreshPrice() {
    try {
      const response = await apiFetch('/pricing/btc-eur', { method: 'GET' });
      if (response && response.data && response.data.price) {
        priceFeeds.BTC_EUR = Number(response.data.price);
        document.getElementById('btcEurPrice').textContent = `${priceFeeds.BTC_EUR.toFixed(2)} EUR`;
      }
    } catch (error) {
      console.warn('No se pudo actualizar el precio BTC/EUR:', error.message);
    }
  }

  async function refreshLoans() {
    try {
      const response = await apiFetch('/loans', { method: 'GET' });
      renderLoans(response.data || []);
    } catch (error) {
      console.error('No se pudieron obtener los préstamos', error);
    }
  }

  async function refreshMetrics() {
    try {
      const response = await apiFetch('/metrics', { method: 'GET' });
      const metrics = response.data || {};
      metricsEl.textContent = `Total: ${metrics.total || 0} · Activos: ${metrics.active || 0} · Reembolsados: ${metrics.repaid || 0} · En default: ${metrics.defaulted || 0}`;
    } catch (error) {
      metricsEl.textContent = 'No disponible';
    }
  }

  connectWalletBtn.addEventListener('click', async () => {
    if (!window.ethereum) {
      alert('Necesitas una wallet compatible con Ethereum (por ejemplo MetaMask).');
      return;
    }
    const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
    account = accounts[0];
    walletAddressEl.textContent = account;
    btcBalanceEl.textContent = `${(Math.random() * 0.5).toFixed(8)} BTC`;
    btcbBalanceEl.textContent = `${(Math.random() * 0.5).toFixed(4)} BTC.b`;
    moneriumStatusEl.textContent = 'Vinculada (sandbox)';
    await refreshLoans();
  });

  ltvSlider.addEventListener('input', () => {
    ltvValue.textContent = `${ltvSlider.value}%`;
    updateSimulation();
  });

  eurAmountInput.addEventListener('input', updateSimulation);
  durationInput.addEventListener('input', updateSimulation);

  function updateSimulation() {
    const eurAmount = Number(eurAmountInput.value);
    const ltv = Number(ltvSlider.value) / 100;
    if (!eurAmount || !ltv) {
      btcRequiredInput.value = '';
      simulationOutput.innerHTML = '<p>Introduce un importe válido en euros.</p>';
      return;
    }
    const btcRequired = eurAmount / priceFeeds.BTC_EUR / ltv;
    btcRequiredInput.value = btcRequired.toFixed(6);
    simulationOutput.innerHTML = `<p>Para recibir ${eurAmount.toFixed(2)} EUR necesitas depositar aproximadamente ${btcRequired.toFixed(6)} BTC.b. El préstamo vencerá en ${durationInput.value} días.</p>`;
  }

  loanForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!account) {
      alert('Conecta tu wallet antes de solicitar un préstamo.');
      return;
    }
    try {
      const eurAmount = Number(eurAmountInput.value);
      const btcRequired = Number(btcRequiredInput.value);
      const duration = Number(durationInput.value);
      const ltv = Number(ltvSlider.value);
      const payload = {
        borrower: account,
        principal: eurAmount,
        collateralBTCb: btcRequired,
        duration: duration * 86400,
        ltv,
        disburseVia: document.getElementById('disburseVia').value,
        iban: document.getElementById('iban').value,
        reference: document.getElementById('reference').value || 'Crypto Loans disbursement',
      };
      const response = await apiFetch('/loans', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      simulationOutput.innerHTML = '<p class="success">Préstamo solicitado correctamente. Sigue las instrucciones del bridge de Avalanche en tu wallet.</p>';
      eurAmountInput.value = '';
      btcRequiredInput.value = '';
      await refreshLoans();
      await refreshMetrics();
      console.info('Loan created', response.data);
    } catch (error) {
      simulationOutput.innerHTML = `<p class="error">No se pudo solicitar el préstamo: ${error.message}</p>`;
    }
  });

  repayForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const loanId = document.getElementById('repayLoanId').value;
    const amount = Number(document.getElementById('repayAmount').value);
    const method = document.getElementById('repayMethod').value;
    if (!loanId || !amount) {
      repayStatus.innerHTML = '<p class="error">Introduce un identificador y una cantidad válida.</p>';
      return;
    }
    try {
      const response = await apiFetch('/repay', {
        method: 'POST',
        body: JSON.stringify({ loanId, amount, via: method }),
      });
      repayStatus.innerHTML = `<p class="success">Repago registrado. Estado actual: ${response.data.status}.</p>`;
      await refreshLoans();
      await refreshMetrics();
    } catch (error) {
      repayStatus.innerHTML = `<p class="error">No se pudo registrar el repago: ${error.message}</p>`;
    }
  });

  function renderLoans(loans) {
    loansTableBody.innerHTML = '';
    loans.forEach((loan) => {
      const row = document.createElement('tr');
      const ltv = loan.currentLtv ? `${(Number(loan.currentLtv) * 100).toFixed(2)}%` : `${loan.ltv || 0}%`;
      const deadline = loan.deadline ? new Date(loan.deadline * 1000).toLocaleString() : '—';
      row.innerHTML = `
        <td>${loan.loanId || loan.id}</td>
        <td>${Number(loan.principal || 0).toFixed(2)} EUR</td>
        <td>${Number(loan.collateralBTCb || 0).toFixed(6)} BTC.b</td>
        <td>${ltv}</td>
        <td>${loan.status || 'Desconocido'}</td>
        <td>${deadline}</td>
        <td><button data-loan="${loan.loanId}" class="secondary">Historial</button></td>
      `;
      row.querySelector('button').addEventListener('click', () => showLoanHistory(loan.loanId));
      loansTableBody.appendChild(row);
    });
  }

  async function showLoanHistory(loanId) {
    try {
      const response = await apiFetch(`/loans/${loanId}/history`, { method: 'GET' });
      const history = response.data || [];
      const lines = history
        .map((entry) => `• [${new Date(entry.timestamp * 1000).toLocaleString()}] ${entry.event} → ${JSON.stringify(entry.metadata)}`)
        .join('\n');
      alert(`Historial del préstamo ${loanId}:\n${lines || 'Sin eventos registrados.'}`);
    } catch (error) {
      alert(`No se pudo obtener el historial del préstamo ${loanId}: ${error.message}`);
    }
  }

  async function bootstrap() {
    await refreshPrice();
    updateSimulation();
    await refreshLoans();
    await refreshMetrics();
  }

  bootstrap();
})();
