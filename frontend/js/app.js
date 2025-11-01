import {
  connect as wagmiConnect,
  createConfig,
  disconnect as wagmiDisconnect,
  fetchBalance,
  getAccount,
  http,
  readContract,
  reconnect,
  signMessage,
  signTypedData,
  waitForTransactionReceipt,
  watchAccount,
  writeContract,
} from 'https://esm.sh/@wagmi/core@1.4.12';
import { injected, walletConnect } from 'https://esm.sh/@wagmi/connectors@3.1.4';
import { avalanche, avalancheFuji } from 'https://esm.sh/@wagmi/chains@1.4.12';
import { ethers } from 'https://esm.sh/ethers@5.7.2';

const ERC20_ABI = [
  'function allowance(address owner, address spender) view returns (uint256)',
  'function approve(address spender, uint256 amount) returns (bool)',
  'function balanceOf(address account) view returns (uint256)',
  'function decimals() view returns (uint8)',
  'function symbol() view returns (string)',
  'function name() view returns (string)',
  'function nonces(address owner) view returns (uint256)',
  'function permit(address owner, address spender, uint256 value, uint256 deadline, uint8 v, bytes32 r, bytes32 s)',
];

const COORDINATOR_ABI = [
  'function depositCollateral(uint256 amountBTCb, uint256 ltvBps, uint64 duration, bytes bridgeProof) returns (bytes32 loanId, uint256 principalEUR)',
  'function lockOwnershipToken(bytes32 loanId)',
  'function positions(bytes32 loanId) view returns (tuple(address user,uint256 collateralAmount,uint256 vaultShares,uint256 loanPrincipalEUR,uint256 mintedTokens,uint256 ltvBps,uint64 createdAt,uint64 deadline,bytes32 bridgeProofHash,uint8 state))',
];

const DEFAULT_SETTINGS = {
  chain: 'avalanche',
  rpcUrl: undefined,
  walletConnectProjectId: '',
  contracts: {
    loanCoordinator: '',
    btcB: '0x152b9d0FdC40C096757F570A51E494bd4b943E50',
    ownershipToken: '',
  },
  tokens: {
    btcBDecimals: 8,
    ownershipDecimals: 18,
    ownershipName: 'OwnershipToken',
  },
};

const APP_CONFIG = window.APP_CONFIG || {};
const SETTINGS = {
  ...DEFAULT_SETTINGS,
  ...APP_CONFIG,
  contracts: {
    ...DEFAULT_SETTINGS.contracts,
    ...(APP_CONFIG.contracts || {}),
  },
  tokens: {
    ...DEFAULT_SETTINGS.tokens,
    ...(APP_CONFIG.tokens || {}),
  },
};

const TERMS_VERSION = '1';
const TERMS_TEXT =
  'Al solicitar este préstamo confirmas que comprendes los riesgos asociados al uso de criptoactivos como colateral, aceptas la liquidación automática en caso de incumplimiento del LTV pactado y autorizas al coordinador a ejecutar el colateral si fuese necesario. Declaras que los fondos no proceden de actividades ilícitas y que cumplirás con la legislación vigente en materia de prevención de blanqueo de capitales.\nLa solicitud queda sujeta a disponibilidad de liquidez en la plataforma y a verificaciones adicionales de seguridad. El incumplimiento de pagos conlleva cargos adicionales y puede resultar en la liquidación total del colateral aportado.';
const TERMS_HASH = ethers.utils.sha256(ethers.utils.toUtf8Bytes(TERMS_TEXT));
const TERMS_TYPES = {
  EIP712Domain: [
    { name: 'name', type: 'string' },
    { name: 'version', type: 'string' },
    { name: 'chainId', type: 'uint256' },
    { name: 'verifyingContract', type: 'address' },
  ],
  TermsAcceptance: [
    { name: 'wallet', type: 'address' },
    { name: 'termsHash', type: 'bytes32' },
    { name: 'timestamp', type: 'uint256' },
  ],
};

const CHAIN_REGISTRY = {
  avalanche,
  fuji: avalancheFuji,
};

const SELECTED_CHAIN = CHAIN_REGISTRY[SETTINGS.chain] || avalanche;
const FALLBACK_RPC =
  SELECTED_CHAIN.id === avalancheFuji.id
    ? 'https://api.avax-test.network/ext/bc/C/rpc'
    : 'https://api.avax.network/ext/bc/C/rpc';
const RPC_ENDPOINT =
  SETTINGS.rpcUrl || SELECTED_CHAIN.rpcUrls?.public?.http?.[0] || SELECTED_CHAIN.rpcUrls?.default?.http?.[0] || FALLBACK_RPC;

const connectWalletBtn = document.getElementById('connectWallet');
const disconnectWalletBtn = document.getElementById('disconnectWallet');
const connectorSelect = document.getElementById('connectorSelect');
const walletAddressEl = document.getElementById('walletAddress');
const btcBalanceEl = document.getElementById('btcBalance');
const btcbBalanceEl = document.getElementById('btcbBalance');
const btcbAllowanceEl = document.getElementById('btcbAllowance');
const ownershipAllowanceEl = document.getElementById('ownershipAllowance');
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
const approveBtcForm = document.getElementById('approveBtcForm');
const approveBtcAmount = document.getElementById('approveBtcAmount');
const approveOwnershipForm = document.getElementById('approveOwnershipForm');
const approveOwnershipAmount = document.getElementById('approveOwnershipAmount');
const depositCollateralForm = document.getElementById('depositCollateralForm');
const depositAmount = document.getElementById('depositAmount');
const depositLtv = document.getElementById('depositLtv');
const depositDuration = document.getElementById('depositDuration');
const depositBridgeProof = document.getElementById('depositBridgeProof');
const depositStatus = document.getElementById('depositStatus');
const lockOwnershipForm = document.getElementById('lockOwnershipForm');
const lockLoanId = document.getElementById('lockLoanId');
const lockStatus = document.getElementById('lockStatus');
const bridgeStatusForm = document.getElementById('bridgeStatusForm');
const bridgeStatusIdInput = document.getElementById('bridgeStatusId');
const bridgeLiveStatus = document.getElementById('bridgeLiveStatus');
const bridgeWrapForm = document.getElementById('bridgeWrapForm');
const bridgeWrapStatus = document.getElementById('bridgeWrapStatus');
const bridgeWrapLoanId = document.getElementById('bridgeWrapLoanId');
const bridgeWrapTx = document.getElementById('bridgeWrapTx');
const bridgeWrapTarget = document.getElementById('bridgeWrapTarget');
const bridgeWrapNetwork = document.getElementById('bridgeWrapNetwork');
const bridgeUnwrapForm = document.getElementById('bridgeUnwrapForm');
const bridgeUnwrapStatus = document.getElementById('bridgeUnwrapStatus');
const bridgeUnwrapAmount = document.getElementById('bridgeUnwrapAmount');
const bridgeUnwrapBtc = document.getElementById('bridgeUnwrapBtc');
const bridgeUnwrapSource = document.getElementById('bridgeUnwrapSource');
const bridgeUnwrapNetwork = document.getElementById('bridgeUnwrapNetwork');
const bridgeUnwrapLoanId = document.getElementById('bridgeUnwrapLoanId');
const moneriumLinkForm = document.getElementById('moneriumLinkForm');
const moneriumIbanInput = document.getElementById('moneriumIban');
const moneriumUserIdInput = document.getElementById('moneriumUserId');
const moneriumMessageInput = document.getElementById('moneriumMessage');
const moneriumLinkStatus = document.getElementById('moneriumLinkStatus');
const historyStream = document.getElementById('historyStream');
const termsStatusEl = document.getElementById('termsStatus');
const loanTermsCheckbox = document.getElementById('loanTermsCheckbox');
const signTermsButton = document.getElementById('signTermsButton');
const termsSignatureStatus = document.getElementById('termsSignatureStatus');

const API_BASE = SETTINGS.backendUrl || 'http://localhost:8080';
const API_KEY = SETTINGS.apiKey || '';

let wagmiConfig;
let connectors = [];
let connectorsById = new Map();
let account;
let priceFeeds = {
  BTC_EUR: 35000,
};
let moneriumLink;
let tokenMetadata = {
  btcBDecimals: SETTINGS.tokens.btcBDecimals,
  ownershipDecimals: SETTINGS.tokens.ownershipDecimals,
  btcBSymbol: 'BTC.b',
  btcBName: 'BTC.b',
  ownershipSymbol: 'OWN',
  ownershipName: SETTINGS.tokens.ownershipName || 'OwnershipToken',
};
let historyPollInterval;
let bridgeStatusTimer;
let termsAcceptance;
let storedTermsAcceptance;

function hexFromBase64(input) {
  if (!input) return '0x';
  if (input.startsWith('0x')) return input;
  try {
    const sanitized = input.trim();
    if (!sanitized) return '0x';
    const binary = atob(sanitized);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return `0x${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`;
  } catch (error) {
    throw new Error('Bridge proof inválido, asegúrate de usar base64 o 0x');
  }
}

function getTermsDomain() {
  const override = APP_CONFIG.termsDomain || {};
  const chainId = Number(override.chainId || APP_CONFIG.termsChainId || SELECTED_CHAIN.id);
  const verifier =
    override.verifyingContract ||
    APP_CONFIG.termsVerifier ||
    SETTINGS.contracts.loanCoordinator ||
    ethers.constants.AddressZero;
  let verifyingContract = verifier;
  try {
    verifyingContract = ethers.utils.getAddress(verifier);
  } catch (error) {
    verifyingContract = ethers.constants.AddressZero;
  }
  return {
    name: override.name || 'CryptoLoans Terms',
    version: override.version || TERMS_VERSION,
    chainId,
    verifyingContract,
  };
}

function resetTermsAcceptance(options = {}) {
  const { clearCheckbox = false } = options;
  termsAcceptance = undefined;
  if (termsSignatureStatus) {
    termsSignatureStatus.textContent = '';
    termsSignatureStatus.className = 'hint';
  }
  if (clearCheckbox && loanTermsCheckbox) {
    loanTermsCheckbox.checked = false;
  }
  updateTermsControlsState();
}

function updateTermsStatusDisplay(record) {
  if (!termsStatusEl) return;
  if (record && record.acceptedAt) {
    const acceptedAt = new Date(record.acceptedAt * 1000).toLocaleString();
    const hashPreview = record.termsHash ? `${record.termsHash.slice(0, 12)}…` : '—';
    termsStatusEl.textContent = `Firmado el ${acceptedAt} · ${hashPreview}`;
  } else {
    termsStatusEl.textContent = 'Pendiente';
  }
}

async function fetchTermsAcceptanceStatus(wallet) {
  if (!wallet) return null;
  try {
    const response = await apiFetch(`/terms/${wallet}`, { method: 'GET' });
    return response.data || response;
  } catch (error) {
    if (error.message && error.message.includes('404')) {
      return null;
    }
    throw error;
  }
}

async function syncTermsAcceptance(wallet) {
  if (!wallet) {
    storedTermsAcceptance = undefined;
    updateTermsStatusDisplay(null);
    resetTermsAcceptance({ clearCheckbox: true });
    return;
  }
  try {
    const record = await fetchTermsAcceptanceStatus(wallet);
    storedTermsAcceptance = record || undefined;
    updateTermsStatusDisplay(record || null);
  } catch (error) {
    if (termsSignatureStatus) {
      termsSignatureStatus.className = 'hint error';
      termsSignatureStatus.textContent = `No se pudo consultar la aceptación: ${error.message}`;
    }
    storedTermsAcceptance = undefined;
    updateTermsStatusDisplay(null);
  }
}

function updateTermsControlsState() {
  if (signTermsButton) {
    const walletConnected = Boolean(account && account.address);
    const checkboxChecked = loanTermsCheckbox ? loanTermsCheckbox.checked : false;
    signTermsButton.disabled = !walletConnected || !checkboxChecked;
  }
}

async function handleTermsSignature(event) {
  event.preventDefault();
  if (!account || !account.address) {
    if (termsSignatureStatus) {
      termsSignatureStatus.className = 'hint error';
      termsSignatureStatus.textContent = 'Conecta tu wallet antes de firmar los términos.';
    }
    return;
  }
  if (!loanTermsCheckbox || !loanTermsCheckbox.checked) {
    if (termsSignatureStatus) {
      termsSignatureStatus.className = 'hint error';
      termsSignatureStatus.textContent = 'Debes aceptar los términos antes de firmar.';
    }
    return;
  }
  const domain = getTermsDomain();
  const timestamp = Math.floor(Date.now() / 1000);
  const message = {
    wallet: account.address,
    termsHash: TERMS_HASH,
    timestamp,
  };
  try {
    if (termsSignatureStatus) {
      termsSignatureStatus.className = 'hint';
      termsSignatureStatus.textContent = 'Solicitando firma…';
    }
    const signature = await signTypedData(wagmiConfig, {
      account: account.address,
      domain,
      types: TERMS_TYPES,
      primaryType: 'TermsAcceptance',
      message,
      chainId: domain.chainId,
    });
    termsAcceptance = {
      wallet: account.address,
      termsHash: TERMS_HASH,
      timestamp,
      signature,
    };
    if (termsSignatureStatus) {
      termsSignatureStatus.className = 'hint success';
      termsSignatureStatus.textContent = `Firma registrada (${new Date(timestamp * 1000).toLocaleString()}).`;
    }
  } catch (error) {
    termsAcceptance = undefined;
    if (termsSignatureStatus) {
      termsSignatureStatus.className = 'hint error';
      termsSignatureStatus.textContent = `No se pudo firmar los términos: ${error.message}`;
    }
  }
}

async function apiFetch(path, options) {
  const opts = Object.assign(
    {
      headers: {
        'Content-Type': 'application/json',
      },
    },
    options || {},
  );
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

function formatAllowances(allowance, decimals, symbol) {
  if (allowance == null) return '—';
  const normalized = typeof allowance === 'bigint' ? allowance.toString() : allowance;
  return `${ethers.utils.formatUnits(normalized, decimals)} ${symbol}`;
}

async function ensureTokenMetadata() {
  if (!account || !account.address) return;
  const { btcB, ownershipToken } = SETTINGS.contracts;
  try {
    if (btcB) {
      const [decimals, symbol, name] = await Promise.all([
        readContract(wagmiConfig, {
          address: btcB,
          abi: ERC20_ABI,
          functionName: 'decimals',
          chainId: SELECTED_CHAIN.id,
        }),
        readContract(wagmiConfig, {
          address: btcB,
          abi: ERC20_ABI,
          functionName: 'symbol',
          chainId: SELECTED_CHAIN.id,
        }),
        readContract(wagmiConfig, {
          address: btcB,
          abi: ERC20_ABI,
          functionName: 'name',
          chainId: SELECTED_CHAIN.id,
        }),
      ]);
      tokenMetadata.btcBDecimals = Number(decimals);
      tokenMetadata.btcBSymbol = symbol;
      tokenMetadata.btcBName = name;
    }
  } catch (error) {
    console.warn('No se pudieron obtener los metadatos de BTC.b:', error.message);
  }
  try {
    if (ownershipToken) {
      const [decimals, symbol, name] = await Promise.all([
        readContract(wagmiConfig, {
          address: ownershipToken,
          abi: ERC20_ABI,
          functionName: 'decimals',
          chainId: SELECTED_CHAIN.id,
        }),
        readContract(wagmiConfig, {
          address: ownershipToken,
          abi: ERC20_ABI,
          functionName: 'symbol',
          chainId: SELECTED_CHAIN.id,
        }),
        readContract(wagmiConfig, {
          address: ownershipToken,
          abi: ERC20_ABI,
          functionName: 'name',
          chainId: SELECTED_CHAIN.id,
        }),
      ]);
      tokenMetadata.ownershipDecimals = Number(decimals);
      tokenMetadata.ownershipSymbol = symbol;
      tokenMetadata.ownershipName = name;
    }
  } catch (error) {
    console.warn('No se pudieron obtener los metadatos de OwnershipToken:', error.message);
  }
}

async function refreshBalances() {
  if (!account || !account.address) return;
  const { btcB, ownershipToken } = SETTINGS.contracts;
  try {
    if (btcB) {
      const balance = await fetchBalance(wagmiConfig, {
        address: account.address,
        token: btcB,
        chainId: SELECTED_CHAIN.id,
      });
      btcBalanceEl.textContent = `${balance.formatted} ${balance.symbol}`;
    } else {
      btcBalanceEl.textContent = 'Contrato BTC.b no configurado';
    }
  } catch (error) {
    btcBalanceEl.textContent = `Error: ${error.message}`;
  }
  try {
    if (ownershipToken) {
      const balance = await fetchBalance(wagmiConfig, {
        address: account.address,
        token: ownershipToken,
        chainId: SELECTED_CHAIN.id,
      });
      btcbBalanceEl.textContent = `${balance.formatted} ${balance.symbol}`;
    } else {
      btcbBalanceEl.textContent = 'OwnershipToken no configurado';
    }
  } catch (error) {
    btcbBalanceEl.textContent = `Error: ${error.message}`;
  }
}

async function refreshAllowances() {
  if (!account || !account.address) return;
  const { loanCoordinator, btcB, ownershipToken } = SETTINGS.contracts;
  if (!loanCoordinator) {
    btcbAllowanceEl.textContent = 'Coordinador no configurado';
    ownershipAllowanceEl.textContent = 'Coordinador no configurado';
    return;
  }
  try {
    if (btcB) {
      const allowance = await readContract(wagmiConfig, {
        address: btcB,
        abi: ERC20_ABI,
        functionName: 'allowance',
        args: [account.address, loanCoordinator],
        chainId: SELECTED_CHAIN.id,
      });
      btcbAllowanceEl.textContent = formatAllowances(
        allowance,
        tokenMetadata.btcBDecimals,
        tokenMetadata.btcBSymbol,
      );
    }
  } catch (error) {
    btcbAllowanceEl.textContent = `Error: ${error.message}`;
  }
  try {
    if (ownershipToken) {
      const allowance = await readContract(wagmiConfig, {
        address: ownershipToken,
        abi: ERC20_ABI,
        functionName: 'allowance',
        args: [account.address, loanCoordinator],
        chainId: SELECTED_CHAIN.id,
      });
      ownershipAllowanceEl.textContent = formatAllowances(
        allowance,
        tokenMetadata.ownershipDecimals,
        tokenMetadata.ownershipSymbol,
      );
    }
  } catch (error) {
    ownershipAllowanceEl.textContent = `Error: ${error.message}`;
  }
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
    const loans = response.data || [];
    renderLoans(loans);
    await refreshHistoryStream(loans.map((loan) => loan.loanId || loan.id));
  } catch (error) {
    console.error('No se pudieron obtener los préstamos', error);
  }
}

async function refreshMetrics() {
  try {
    const response = await apiFetch('/metrics', { method: 'GET' });
    const metrics = response.data || {};
    metricsEl.textContent = `Total: ${metrics.total || 0} · Activos: ${metrics.active || 0} · Reembolsados: ${
      metrics.repaid || 0
    } · En default: ${metrics.defaulted || 0}`;
  } catch (error) {
    metricsEl.textContent = 'No disponible';
  }
}

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
  simulationOutput.innerHTML = `<p>Para recibir ${eurAmount.toFixed(2)} EUR necesitas depositar aproximadamente ${btcRequired.toFixed(
    6,
  )} BTC.b. El préstamo vencerá en ${durationInput.value} días.</p>`;
}

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
        <td><button data-loan="${loan.loanId || loan.id}" class="secondary">Historial</button></td>
      `;
    row.querySelector('button').addEventListener('click', () => showLoanHistory(loan.loanId || loan.id));
    loansTableBody.appendChild(row);
  });
}

async function showLoanHistory(loanId) {
  if (!loanId) return;
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

async function refreshHistoryStream(loanIds) {
  if (!historyStream) return;
  try {
    const historyChunks = await Promise.all(
      (loanIds || []).map(async (loanId) => {
        if (!loanId) return [];
        const response = await apiFetch(`/loans/${loanId}/history`, { method: 'GET' });
        return (response.data || []).map((event) => ({ loanId, ...event }));
      }),
    );
    const flattened = historyChunks.flat().sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
    historyStream.innerHTML = '';
    flattened.slice(-20).forEach((entry) => {
      const line = document.createElement('div');
      line.className = 'history-entry';
      line.innerHTML = `<strong>${entry.loanId}</strong> · ${new Date(entry.timestamp * 1000).toLocaleString()} · ${entry.event}<pre>${JSON.stringify(
        entry.metadata,
        null,
        2,
      )}</pre>`;
      historyStream.appendChild(line);
    });
  } catch (error) {
    historyStream.innerHTML = `<p class="error">No se pudieron sincronizar los eventos: ${error.message}</p>`;
  }
}

async function connectWallet() {
  const selected = connectorSelect?.value || 'auto';
  const connector = connectorsById.get(selected) || connectors[0];
  if (!connector) {
    alert('No hay conectores disponibles.');
    return;
  }
  try {
    await wagmiConnect(wagmiConfig, {
      connector,
      chainId: SELECTED_CHAIN.id,
    });
  } catch (error) {
    alert(`No se pudo conectar la wallet: ${error.message}`);
  }
}

async function disconnectWallet() {
  try {
    await wagmiDisconnect(wagmiConfig);
    account = undefined;
    walletAddressEl.textContent = 'No conectada';
    btcBalanceEl.textContent = '0.00000000';
    btcbBalanceEl.textContent = '0.0000';
    btcbAllowanceEl.textContent = '—';
    ownershipAllowanceEl.textContent = '—';
    moneriumLink = undefined;
    moneriumStatusEl.textContent = 'No vinculada';
    moneriumMessageInput.value = generateMoneriumMessage('', '');
    moneriumUserIdInput.value = '';
    moneriumLinkStatus.innerHTML = '';
    stopHistoryPolling();
    storedTermsAcceptance = undefined;
    resetTermsAcceptance({ clearCheckbox: true });
    updateTermsStatusDisplay(null);
    updateTermsControlsState();
  } catch (error) {
    console.warn('No se pudo desconectar la wallet:', error.message);
  }
}

async function handleAccountChanged(newAccount) {
  account = newAccount;
  if (account && account.address) {
    walletAddressEl.textContent = account.address;
    await ensureTokenMetadata();
    await refreshBalances();
    await refreshAllowances();
    moneriumMessageInput.value = generateMoneriumMessage('', account.address);
    await syncMoneriumLink();
    resetTermsAcceptance({ clearCheckbox: true });
    await syncTermsAcceptance(account.address);
    updateTermsControlsState();
    startHistoryPolling();
  } else {
    walletAddressEl.textContent = 'No conectada';
    moneriumLink = undefined;
    moneriumStatusEl.textContent = 'No vinculada';
    moneriumMessageInput.value = generateMoneriumMessage('', '');
    moneriumUserIdInput.value = '';
    moneriumLinkStatus.innerHTML = '';
    storedTermsAcceptance = undefined;
    resetTermsAcceptance({ clearCheckbox: true });
    updateTermsStatusDisplay(null);
    updateTermsControlsState();
    stopHistoryPolling();
  }
}

function startHistoryPolling() {
  stopHistoryPolling();
  historyPollInterval = window.setInterval(() => refreshLoans(), 15000);
}

function stopHistoryPolling() {
  if (historyPollInterval) {
    window.clearInterval(historyPollInterval);
    historyPollInterval = undefined;
  }
}

function setupConnectorOptions() {
  connectorSelect.innerHTML = '';
  if (!connectors.length) {
    const option = document.createElement('option');
    option.value = 'none';
    option.textContent = 'Sin conectores disponibles';
    connectorSelect.appendChild(option);
    connectWalletBtn.disabled = true;
    return;
  }
  connectors.forEach((connector) => {
    const option = document.createElement('option');
    option.value = connector.id;
    option.textContent = connector.name || connector.id;
    connectorSelect.appendChild(option);
  });
  connectWalletBtn.disabled = false;
}

async function handleApprove(event, tokenKey) {
  event.preventDefault();
  if (!account || !account.address) {
    alert('Conecta tu wallet antes de aprobar.');
    return;
  }
  const { loanCoordinator, btcB, ownershipToken } = SETTINGS.contracts;
  if (!loanCoordinator) {
    alert('Configura la dirección del coordinador antes de aprobar.');
    return;
  }
  const isBtc = tokenKey === 'btcB';
  const contractAddress = isBtc ? btcB : ownershipToken;
  if (!contractAddress) {
    alert('Token no configurado.');
    return;
  }
  const amountField = isBtc ? approveBtcAmount : approveOwnershipAmount;
  const decimals = isBtc ? tokenMetadata.btcBDecimals : tokenMetadata.ownershipDecimals;
  const symbol = isBtc ? tokenMetadata.btcBSymbol : tokenMetadata.ownershipSymbol;
  const value = amountField.value || '0';
  try {
    const parsed = ethers.utils.parseUnits(value || '0', decimals);
    const amountRaw = BigInt(parsed.toString());
    const txHash = await writeContract(wagmiConfig, {
      address: contractAddress,
      abi: ERC20_ABI,
      functionName: 'approve',
      args: [loanCoordinator, amountRaw],
      chainId: SELECTED_CHAIN.id,
    });
    if (isBtc) {
      btcbAllowanceEl.textContent = 'Esperando confirmación…';
    } else {
      ownershipAllowanceEl.textContent = 'Esperando confirmación…';
    }
    await waitForTransactionReceipt(wagmiConfig, { hash: txHash, chainId: SELECTED_CHAIN.id });
    await refreshAllowances();
    alert(`Aprobación enviada correctamente (${symbol}).`);
  } catch (error) {
    alert(`No se pudo aprobar ${symbol}: ${error.message}`);
  }
}

async function handleDepositCollateral(event) {
  event.preventDefault();
  if (!account || !account.address) {
    alert('Conecta tu wallet antes de depositar.');
    return;
  }
  const { loanCoordinator } = SETTINGS.contracts;
  if (!loanCoordinator) {
    depositStatus.innerHTML = '<p class="error">Contrato de coordinador no configurado.</p>';
    return;
  }
  const amount = Number(depositAmount.value || 0);
  const ltv = Number(depositLtv.value || 0);
  const durationDays = Number(depositDuration.value || 0);
  if (!amount || amount <= 0) {
    depositStatus.innerHTML = '<p class="error">Introduce un monto válido de BTC.b.</p>';
    return;
  }
  if (!ltv || ltv <= 0) {
    depositStatus.innerHTML = '<p class="error">Introduce un LTV válido en puntos básicos.</p>';
    return;
  }
  if (!durationDays || durationDays <= 0) {
    depositStatus.innerHTML = '<p class="error">Introduce una duración en días.</p>';
    return;
  }
  try {
    const amountRaw = BigInt(ethers.utils.parseUnits(String(amount), tokenMetadata.btcBDecimals).toString());
    const durationSeconds = BigInt(durationDays) * BigInt(86400);
    const bridgeProofHex = hexFromBase64(depositBridgeProof.value || '');
    depositStatus.innerHTML = '<p>Enviando transacción…</p>';
    const hash = await writeContract(wagmiConfig, {
      address: loanCoordinator,
      abi: COORDINATOR_ABI,
      functionName: 'depositCollateral',
      args: [amountRaw, BigInt(ltv), durationSeconds, bridgeProofHex],
      chainId: SELECTED_CHAIN.id,
    });
    await waitForTransactionReceipt(wagmiConfig, { hash, chainId: SELECTED_CHAIN.id });
    depositStatus.innerHTML = '<p class="success">Colateral depositado. Revisa los eventos del préstamo.</p>';
    await refreshBalances();
    await refreshAllowances();
    await refreshLoans();
  } catch (error) {
    depositStatus.innerHTML = `<p class="error">Fallo al depositar: ${error.message}</p>`;
  }
}

async function handleLockOwnership(event) {
  event.preventDefault();
  if (!account || !account.address) {
    alert('Conecta tu wallet antes de bloquear tokens.');
    return;
  }
  const { loanCoordinator } = SETTINGS.contracts;
  const { ownershipToken } = SETTINGS.contracts;
  if (!loanCoordinator) {
    lockStatus.innerHTML = '<p class="error">Contrato de coordinador no configurado.</p>';
    return;
  }
  if (!ownershipToken) {
    lockStatus.innerHTML = '<p class="error">OwnershipToken no configurado.</p>';
    return;
  }
  const loanIdRaw = lockLoanId.value.trim();
  if (!loanIdRaw) {
    lockStatus.innerHTML = '<p class="error">Introduce un ID de préstamo válido.</p>';
    return;
  }
  try {
    const loanId = loanIdRaw.startsWith('0x') ? loanIdRaw : `0x${loanIdRaw}`;
    lockStatus.innerHTML = '<p>Preparando bloqueo…</p>';
    const position = await readContract(wagmiConfig, {
      address: loanCoordinator,
      abi: COORDINATOR_ABI,
      functionName: 'positions',
      args: [loanId],
      chainId: SELECTED_CHAIN.id,
    });
    const borrower = (position?.user || position?.[0] || '').toLowerCase();
    if (borrower !== account.address.toLowerCase()) {
      lockStatus.innerHTML = '<p class="error">El préstamo no pertenece a la cuenta conectada.</p>';
      return;
    }
    const mintedRaw = position?.mintedTokens ?? position?.[4] ?? 0n;
    const mintedTokens = typeof mintedRaw === 'bigint' ? mintedRaw : BigInt(mintedRaw || 0);
    if (mintedTokens === 0n) {
      lockStatus.innerHTML = '<p class="error">No hay OwnershipToken emitido para este préstamo.</p>';
      return;
    }
    const currentAllowance = await readContract(wagmiConfig, {
      address: ownershipToken,
      abi: ERC20_ABI,
      functionName: 'allowance',
      args: [account.address, loanCoordinator],
      chainId: SELECTED_CHAIN.id,
    });
    if (BigInt(currentAllowance) < mintedTokens) {
      lockStatus.innerHTML = '<p>Firmando permit…</p>';
      const [nonce, tokenName] = await Promise.all([
        readContract(wagmiConfig, {
          address: ownershipToken,
          abi: ERC20_ABI,
          functionName: 'nonces',
          args: [account.address],
          chainId: SELECTED_CHAIN.id,
        }),
        tokenMetadata.ownershipName
          ? Promise.resolve(tokenMetadata.ownershipName)
          : readContract(wagmiConfig, {
              address: ownershipToken,
              abi: ERC20_ABI,
              functionName: 'name',
              chainId: SELECTED_CHAIN.id,
            }),
      ]);
      const deadlineSeconds = Math.floor(Date.now() / 1000) + 3600;
      const domain = {
        name: tokenName || tokenMetadata.ownershipName || tokenMetadata.ownershipSymbol,
        version: '1',
        chainId: SELECTED_CHAIN.id,
        verifyingContract: ownershipToken,
      };
      const types = {
        Permit: [
          { name: 'owner', type: 'address' },
          { name: 'spender', type: 'address' },
          { name: 'value', type: 'uint256' },
          { name: 'nonce', type: 'uint256' },
          { name: 'deadline', type: 'uint256' },
        ],
      };
      const message = {
        owner: account.address,
        spender: loanCoordinator,
        value: mintedTokens.toString(),
        nonce: BigInt(nonce).toString(),
        deadline: deadlineSeconds.toString(),
      };
      const signature = await signTypedData(wagmiConfig, {
        account: account.address,
        domain,
        types,
        primaryType: 'Permit',
        message,
        chainId: SELECTED_CHAIN.id,
      });
      const { v, r, s } = ethers.utils.splitSignature(signature);
      lockStatus.innerHTML = '<p>Enviando permit…</p>';
      const permitHash = await writeContract(wagmiConfig, {
        address: ownershipToken,
        abi: ERC20_ABI,
        functionName: 'permit',
        args: [account.address, loanCoordinator, mintedTokens, BigInt(deadlineSeconds), v, r, s],
        chainId: SELECTED_CHAIN.id,
      });
      await waitForTransactionReceipt(wagmiConfig, { hash: permitHash, chainId: SELECTED_CHAIN.id });
    }
    lockStatus.innerHTML = '<p>Enviando transacción…</p>';
    const hash = await writeContract(wagmiConfig, {
      address: loanCoordinator,
      abi: COORDINATOR_ABI,
      functionName: 'lockOwnershipToken',
      args: [loanId],
      chainId: SELECTED_CHAIN.id,
    });
    await waitForTransactionReceipt(wagmiConfig, { hash, chainId: SELECTED_CHAIN.id });
    lockStatus.innerHTML = '<p class="success">OwnershipToken bloqueado correctamente.</p>';
    await refreshBalances();
    await refreshAllowances();
    await refreshLoans();
  } catch (error) {
    lockStatus.innerHTML = `<p class="error">No se pudo bloquear el token: ${error.message}</p>`;
  }
}

function renderBridgeResult(container, data) {
  if (!container) return;
  container.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
  const txId = data?.transactionId || data?.id;
  if (txId) {
    bridgeStatusIdInput.value = txId;
    pollBridgeStatus(txId);
  }
}

function scheduleBridgePolling(txId) {
  if (!txId) return;
  if (bridgeStatusTimer) {
    window.clearTimeout(bridgeStatusTimer);
  }
  bridgeStatusTimer = window.setTimeout(() => pollBridgeStatus(txId), 15000);
}

async function pollBridgeStatus(txId) {
  if (!txId) return;
  try {
    bridgeLiveStatus.innerHTML = '<p>Consultando estado…</p>';
    const result = await apiFetch(`/bridge/status?id=${encodeURIComponent(txId)}`, { method: 'GET' });
    bridgeLiveStatus.innerHTML = `<pre>${JSON.stringify(result.data, null, 2)}</pre>`;
    scheduleBridgePolling(txId);
  } catch (error) {
    bridgeLiveStatus.innerHTML = `<p class="error">No se pudo obtener el estado: ${error.message}</p>`;
  }
}

async function handleBridgeStatus(event) {
  event.preventDefault();
  const txId = bridgeStatusIdInput.value.trim();
  if (!txId) {
    bridgeLiveStatus.innerHTML = '<p class="error">Introduce un identificador válido.</p>';
    return;
  }
  await pollBridgeStatus(txId);
}

async function handleBridgeWrap(event) {
  event.preventDefault();
  if (!bridgeWrapTx.value.trim()) {
    bridgeWrapStatus.innerHTML = '<p class="error">Introduce el hash de la transacción de Bitcoin.</p>';
    return;
  }
  if (!bridgeWrapTarget.value.trim() && !account?.address) {
    bridgeWrapStatus.innerHTML = '<p class="error">Especifica la dirección de destino en Avalanche.</p>';
    return;
  }
  try {
    const payload = {
      btcTxId: bridgeWrapTx.value.trim(),
      targetAddress: bridgeWrapTarget.value.trim() || account?.address || '',
      network: bridgeWrapNetwork.value,
      loanId: bridgeWrapLoanId.value.trim() || undefined,
    };
    const result = await apiFetch('/bridge/wrap', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    renderBridgeResult(bridgeWrapStatus, result.data || result);
    await refreshLoans();
  } catch (error) {
    bridgeWrapStatus.innerHTML = `<p class="error">No se pudo iniciar el wrap: ${error.message}</p>`;
  }
}

async function handleBridgeUnwrap(event) {
  event.preventDefault();
  if (!bridgeUnwrapAmount.value || Number(bridgeUnwrapAmount.value) <= 0) {
    bridgeUnwrapStatus.innerHTML = '<p class="error">Introduce un monto BTC.b válido.</p>';
    return;
  }
  if (!bridgeUnwrapBtc.value.trim()) {
    bridgeUnwrapStatus.innerHTML = '<p class="error">Introduce la dirección BTC destino.</p>';
    return;
  }
  if (!bridgeUnwrapSource.value.trim() && !account?.address) {
    bridgeUnwrapStatus.innerHTML = '<p class="error">Especifica la dirección fuente de BTC.b.</p>';
    return;
  }
  try {
    const payload = {
      amount: Number(bridgeUnwrapAmount.value || 0),
      btcAddress: bridgeUnwrapBtc.value.trim(),
      sourceAddress: bridgeUnwrapSource.value.trim() || account?.address || '',
      network: bridgeUnwrapNetwork.value,
      loanId: bridgeUnwrapLoanId.value.trim() || undefined,
    };
    const result = await apiFetch('/bridge/unwrap', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    renderBridgeResult(bridgeUnwrapStatus, result.data || result);
    await refreshLoans();
  } catch (error) {
    bridgeUnwrapStatus.innerHTML = `<p class="error">No se pudo iniciar el unwrap: ${error.message}</p>`;
  }
}

function generateMoneriumMessage(iban, address) {
  const timestamp = new Date().toISOString();
  return `Vinculación Monerium\nIBAN: ${iban}\nWallet: ${address || 'sin wallet'}\nTimestamp: ${timestamp}`;
}

async function fetchMoneriumLink(wallet) {
  if (!wallet) return null;
  try {
    const response = await apiFetch(`/monerium/link/${wallet}`, { method: 'GET' });
    return response.data || response;
  } catch (error) {
    if (error.message.includes('404')) {
      return null;
    }
    throw error;
  }
}

async function syncMoneriumLink() {
  if (!account || !account.address) {
    moneriumLink = undefined;
    moneriumStatusEl.textContent = 'No vinculada';
    moneriumMessageInput.value = generateMoneriumMessage('', '');
    return;
  }
  try {
    const record = await fetchMoneriumLink(account.address);
    if (record) {
      moneriumLink = record;
      moneriumStatusEl.textContent = `Vinculada (${record.iban})`;
      moneriumMessageInput.value = generateMoneriumMessage(record.iban, account.address);
      if (record.moneriumUserId) {
        moneriumUserIdInput.value = record.moneriumUserId;
      }
      const hashPreview = record.bindingHash ? `${record.bindingHash.slice(0, 12)}…` : '—';
      moneriumLinkStatus.innerHTML = `<p class="success">Cuenta sincronizada. Hash: ${hashPreview}</p>`;
    } else {
      moneriumLink = undefined;
      moneriumStatusEl.textContent = 'No vinculada';
      moneriumMessageInput.value = generateMoneriumMessage('', account.address);
      moneriumLinkStatus.innerHTML = '<p class="warning">No hay una vinculación registrada.</p>';
    }
  } catch (error) {
    moneriumLinkStatus.innerHTML = `<p class="error">No se pudo consultar el enlace de Monerium: ${error.message}</p>`;
    moneriumStatusEl.textContent = 'Estado desconocido';
  }
}

async function handleMoneriumLink(event) {
  event.preventDefault();
  if (!account || !account.address) {
    moneriumLinkStatus.innerHTML = '<p class="error">Conecta tu wallet antes de vincular Monerium.</p>';
    return;
  }
  const iban = moneriumIbanInput.value.trim();
  if (!iban) {
    moneriumLinkStatus.innerHTML = '<p class="error">Introduce un IBAN válido.</p>';
    return;
  }
  const moneriumUserId = moneriumUserIdInput.value.trim();
  if (!moneriumUserId) {
    moneriumLinkStatus.innerHTML = '<p class="error">Introduce el ID de usuario de Monerium.</p>';
    return;
  }
  const message = generateMoneriumMessage(iban, account.address);
  moneriumMessageInput.value = message;
  try {
    const signature = await signMessage(wagmiConfig, {
      message,
      chainId: SELECTED_CHAIN.id,
    });
    const response = await apiFetch('/monerium/link', {
      method: 'POST',
      body: JSON.stringify({
        iban,
        moneriumUserId,
        message,
        signature,
        wallet: account.address,
      }),
    });
    const record = response.data || response;
    const hashPreview = record.bindingHash ? `${record.bindingHash.slice(0, 12)}…` : '—';
    moneriumLinkStatus.innerHTML = `<p class="success">Cuenta vinculada correctamente. Hash: ${hashPreview}</p>`;
    moneriumUserIdInput.value = record.moneriumUserId || moneriumUserId;
    await syncMoneriumLink();
  } catch (error) {
    moneriumLinkStatus.innerHTML = `<p class="error">No se pudo vincular la cuenta: ${error.message}</p>`;
  }
}

function setupEventListeners() {
  connectWalletBtn.addEventListener('click', connectWallet);
  disconnectWalletBtn.addEventListener('click', disconnectWallet);
  if (loanTermsCheckbox) {
    loanTermsCheckbox.addEventListener('change', () => {
      if (!loanTermsCheckbox.checked) {
        resetTermsAcceptance();
      }
      updateTermsControlsState();
    });
  }
  if (signTermsButton) {
    signTermsButton.addEventListener('click', handleTermsSignature);
  }
  ltvSlider.addEventListener('input', () => {
    ltvValue.textContent = `${ltvSlider.value}%`;
    updateSimulation();
  });
  eurAmountInput.addEventListener('input', updateSimulation);
  durationInput.addEventListener('input', updateSimulation);
  loanForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!account || !account.address) {
      alert('Conecta tu wallet antes de solicitar un préstamo.');
      return;
    }
    if (!loanTermsCheckbox || !loanTermsCheckbox.checked) {
      if (termsSignatureStatus) {
        termsSignatureStatus.className = 'hint error';
        termsSignatureStatus.textContent = 'Debes aceptar los términos antes de solicitar el préstamo.';
      }
      return;
    }
    if (termsAcceptance && termsAcceptance.wallet?.toLowerCase() !== account.address.toLowerCase()) {
      termsAcceptance = undefined;
    }
    if (!termsAcceptance || !termsAcceptance.signature) {
      if (termsSignatureStatus) {
        termsSignatureStatus.className = 'hint error';
        termsSignatureStatus.textContent = 'Firma los términos y condiciones antes de continuar.';
      }
      return;
    }
    try {
      const eurAmount = Number(eurAmountInput.value);
      const btcRequired = Number(btcRequiredInput.value);
      const duration = Number(durationInput.value);
      const ltv = Number(ltvSlider.value);
      const payload = {
        borrower: account.address,
        principal: eurAmount,
        collateralBTCb: btcRequired,
        duration: duration * 86400,
        ltv,
        disburseVia: document.getElementById('disburseVia').value,
        iban: document.getElementById('iban').value,
        reference: document.getElementById('reference').value || 'Crypto Loans disbursement',
        collateralRaw: ethers.utils.parseUnits(String(btcRequired || 0), tokenMetadata.btcBDecimals).toString(),
        principalRaw: ethers.utils.parseUnits(String(eurAmount || 0), 18).toString(),
        bridgeProof: depositBridgeProof.value || '',
        termsAcceptance: {
          wallet: account.address,
          termsHash: TERMS_HASH,
          timestamp: termsAcceptance.timestamp,
          signature: termsAcceptance.signature,
          termsVersion: TERMS_VERSION,
        },
      };
      const response = await apiFetch('/loans', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      simulationOutput.innerHTML = '<p class="success">Préstamo solicitado correctamente. Sigue las instrucciones del bridge de Avalanche en tu wallet.</p>';
      eurAmountInput.value = '';
      btcRequiredInput.value = '';
      if (termsSignatureStatus) {
        termsSignatureStatus.className = 'hint success';
        termsSignatureStatus.textContent = 'Aceptación enviada correctamente.';
      }
      await refreshLoans();
      await refreshMetrics();
      await syncTermsAcceptance(account.address);
      console.info('Loan created', response.data);
    } catch (error) {
      simulationOutput.innerHTML = `<p class="error">No se pudo solicitar el préstamo: ${error.message}</p>`;
      if (termsSignatureStatus) {
        termsSignatureStatus.className = 'hint error';
        termsSignatureStatus.textContent = `Error al enviar la aceptación: ${error.message}`;
      }
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
  approveBtcForm.addEventListener('submit', (event) => handleApprove(event, 'btcB'));
  approveOwnershipForm.addEventListener('submit', (event) => handleApprove(event, 'ownership'));
  depositCollateralForm.addEventListener('submit', handleDepositCollateral);
  lockOwnershipForm.addEventListener('submit', handleLockOwnership);
  bridgeStatusForm.addEventListener('submit', handleBridgeStatus);
  bridgeWrapForm.addEventListener('submit', handleBridgeWrap);
  bridgeUnwrapForm.addEventListener('submit', handleBridgeUnwrap);
  moneriumLinkForm.addEventListener('submit', handleMoneriumLink);
  updateTermsControlsState();
}

async function initialiseWagmi() {
  connectors = [
    injected({ shimDisconnect: true }),
  ];
  connectorsById = new Map(connectors.map((connector) => [connector.id, connector]));
  if (SETTINGS.walletConnectProjectId && typeof walletConnect === 'function') {
    const walletConnectConnector = walletConnect({
      projectId: SETTINGS.walletConnectProjectId,
      metadata: {
        name: 'Crypto Loans',
        description: 'Préstamos colateralizados con BTC.b sobre Avalanche',
        url: window.location.origin,
        icons: ['https://cryptoloans.example/icon.png'],
      },
      showQrModal: true,
    });
    connectors.push(walletConnectConnector);
    connectorsById.set(walletConnectConnector.id, walletConnectConnector);
  }
  wagmiConfig = createConfig({
    chains: [SELECTED_CHAIN],
    connectors,
    transports: {
      [SELECTED_CHAIN.id]: http(RPC_ENDPOINT),
    },
    ssr: false,
  });
  setupConnectorOptions();
  watchAccount(wagmiConfig, {
    onChange: handleAccountChanged,
  });
  await reconnect(wagmiConfig);
  await handleAccountChanged(getAccount(wagmiConfig));
}

async function bootstrap() {
  if (!moneriumMessageInput.value) {
    moneriumMessageInput.value = generateMoneriumMessage('', '');
  }
  setupEventListeners();
  await initialiseWagmi();
  await refreshPrice();
  updateSimulation();
  await refreshLoans();
  await refreshMetrics();
  window.setInterval(refreshPrice, 60000);
  window.setInterval(refreshMetrics, 30000);
}

bootstrap();
