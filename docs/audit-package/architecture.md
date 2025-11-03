# Arquitectura de Referencia

Este documento resume la arquitectura técnica actual del sistema de préstamos
Crypto Loans. Sirve como contexto inicial para equipos de auditoría que
revisarán los contratos inteligentes y los componentes backend regulados.

## Visión general

- **Redes soportadas**: Avalanche C-Chain (gestión de colateral BTC.b) y
  Ethereum Mainnet (gestión de liquidez EURe).
- **Dominio on-chain**: Coordinadores de préstamo bifurcados (`AvalancheLoanCoordinator`
  y `EthereumLoanCoordinator`) comunicados mediante mensajería cross-chain.
- **Dominio off-chain**: Backend orquestador Python que integra Monerium para la
  emisión/redención de EURe y Avalanche Bridge para los movimientos BTC.b ↔ BTC.
- **Front-end**: SPA estática que interactúa exclusivamente con el backend y
  expone formularios de originación, seguimiento y repago.

## Componentes on-chain

| Componente | Red | Rol | Dependencias externas |
|------------|-----|-----|-----------------------|
| `AvalancheLoanCoordinator` | Avalanche | Custodia BTC.b, acuña `OwnershipToken`, coordina mensajes hacia Ethereum y gestiona liquidaciones. | Oracle BTC/EUR, Bridge adapter Avalanche ↔ Bitcoin, mensajero CCIP. |
| `EthereumLoanCoordinator` | Ethereum | Registra préstamos, libera EURe, verifica repagos y orquesta devoluciones de colateral. | Oracle BTC/EUR (feed directo), mensajero CCIP, Monerium API vía backend. |
| `ChainlinkPriceOracle` | Ambas | Calcula precio BTC/EUR combinando feeds BTC/USD y EUR/USD (fallback en Ethereum). | Chainlink Data Feeds. |
| `ChainlinkCCIPMessenger` | Ambas | Adaptador CCIP que enruta mensajes entre coordinadores. | Chainlink CCIP Router (IDs configurables). |
| `AvalancheBridgeAdapter` | Avalanche | Envuelve depósitos BTC.b a través de Avalanche Bridge con parámetros de slippage/verificación. | Avalanche Bridge relayer/verifier, DEX para swaps EURe → BTC.b. |

### Flujos principales

1. **Originación**
   - Usuario deposita BTC.b en `AvalancheLoanCoordinator`.
   - El contrato valida LTV y oracle, acuña `OwnershipToken` y emite evento/mensaje CCIP.
   - `EthereumLoanCoordinator` recibe el payload, registra el préstamo y autoriza la entrega de EURe (vía backend → Monerium).

2. **Repago**
   - Backend confirma transferencia EURe de retorno (Monerium) y llama a `EthereumLoanCoordinator.repay`.
   - El coordinador valida el monto, actualiza estado y envía mensaje de liberación.
   - `AvalancheLoanCoordinator` libera BTC.b al prestatario o ejecuta flujo de bridge de vuelta a BTC según instrucciones.

3. **Liquidación**
   - Monitor de riesgo backend detecta LTV crítico, marca el préstamo e invoca `AvalancheLoanCoordinator.liquidate` o envía mensaje desde Ethereum.
   - Se ejecuta venta de colateral vía `AvalancheBridgeAdapter` y se reportan métricas a backend.

## Backend regulado

- Implementado en `backend/server.py` (Python estándar, sin frameworks).
- Endpoints claves: `/loans`, `/repay`, `/monerium/*`, `/bridge/*`, `/pricing/btc-eur`, `/metrics`.
- Integraciones externas:
  - **Monerium**: OAuth2 Client Credentials para emisión/redención EURe.
  - **Avalanche Bridge**: API REST para verificar pruebas y monitorear tránsitos BTC.b/BTC.
  - **Chainlink Price Feeds**: consumo vía web3 provider para validar precios.
- Controles operativos: rate limiting configurable, API Key opcional, monitor de riesgo en segundo plano, almacenamiento SQLite encriptable (se sugiere habilitar discos cifrados en producción).

## Mensajería cross-chain

- El adaptador `ChainlinkCCIPMessenger` valida remitente (`router`, `remoteSender`) y reenvía payloads a los coordinadores.
- Los payloads contienen parámetros de préstamo (`loanId`, `principal`, `ltvBps`, `deadline`, `bridgeProofHash`).
- Permite fallback manual: ambos coordinadores exponen funciones `setMessenger`, `setEthereumLoanManager` / `setKeeper` para intervenciones directas si CCIP no está disponible.

## Operación y monitoreo

- Métricas expuestas vía `/metrics` (Prometheus friendly) con datos de préstamos activos, LTV promedio, colateral en riesgo.
- Alertas: el backend publica eventos cuando se alcanza umbral de riesgo o se marca un default.
- Logs recomendados en stack ELK / Loki + Grafana.

## Consideraciones de seguridad

- Uso extensivo de `Pausable` y `ReentrancyGuard` en coordinadores.
- Roles diferenciados: owner (governance), `ethereumLoanManager`, keepers autorizados.
- Validaciones de oráculo con `ORACLE_TIMEOUT = 1 hour`.
- Configuraciones sensibles (`bridgeAdapter`, `priceOracle`, `messenger`) requieren `onlyOwner`.
- Revisión de parámetros externos: límites de slippage y montos máximos en `AvalancheBridgeAdapter`.

Este resumen debe complementarse con la lectura de los contratos completos y la
suite de pruebas `forge test` para validar los supuestos descritos.
