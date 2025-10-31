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

  let account;
  let fakeLoans = [];

  const priceFeeds = {
    BTC_EUR: 35000,
  };

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
  });

  ltvSlider.addEventListener('input', () => {
    ltvValue.textContent = `${ltvSlider.value}%`;
    updateSimulation();
  });

  eurAmountInput.addEventListener('input', updateSimulation);

  function updateSimulation() {
    const eurAmount = Number(eurAmountInput.value);
    const ltv = Number(ltvSlider.value) / 100;
    if (!eurAmount || !ltv) {
      btcRequiredInput.value = '';
      return;
    }
    const btcRequired = eurAmount / priceFeeds.BTC_EUR / ltv;
    btcRequiredInput.value = btcRequired.toFixed(6);
    simulationOutput.innerHTML = `<p>Para recibir ${eurAmount.toFixed(2)} EUR necesitas depositar aproximadamente ${btcRequired.toFixed(
      6
    )} BTC.b. El préstamo vencerá en ${durationInput.value} días.</p>`;
  }

  loanForm.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!account) {
      alert('Conecta tu wallet antes de solicitar un préstamo.');
      return;
    }
    const eurAmount = Number(eurAmountInput.value);
    const btcRequired = Number(btcRequiredInput.value);
    const duration = Number(durationInput.value);
    const ltv = Number(ltvSlider.value);

    const loanId = `loan-${Date.now()}`;
    const deadline = new Date(Date.now() + duration * 86400000);
    fakeLoans.push({
      id: loanId,
      principal: eurAmount,
      collateral: btcRequired,
      ltv,
      status: 'Activo',
      deadline: deadline.toLocaleString(),
    });
    renderLoans();

    simulationOutput.innerHTML =
      '<p class="success">Préstamo solicitado correctamente. Sigue las instrucciones del bridge de Avalanche en tu wallet.</p>';
  });

  repayForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const loanId = document.getElementById('repayLoanId').value;
    const amount = Number(document.getElementById('repayAmount').value);
    const method = document.getElementById('repayMethod').value;

    const loan = fakeLoans.find((l) => l.id === loanId);
    if (!loan) {
      repayStatus.innerHTML = '<p class="error">No se encontró el préstamo indicado.</p>';
      return;
    }

    loan.status = 'En repago';
    repayStatus.innerHTML = `<p class="success">Repago iniciado con ${amount.toFixed(2)} EURe vía ${
      method === 'wallet' ? 'wallet' : 'transferencia SEPA'
    }.</p>`;
    renderLoans();
  });

  function renderLoans() {
    loansTableBody.innerHTML = '';
    fakeLoans.forEach((loan) => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${loan.id}</td>
        <td>${loan.principal.toFixed(2)} EUR</td>
        <td>${loan.collateral.toFixed(6)} BTC.b</td>
        <td>${loan.status}</td>
        <td>${loan.deadline}</td>
        <td><button data-loan="${loan.id}" class="secondary">Ver detalles</button></td>
      `;
      loansTableBody.appendChild(row);
    });
  }

  updateSimulation();
})();
