# Crypto Loans – Plataforma de préstamos con BTC como colateral

Este repositorio contiene una implementación de referencia basada en el blueprint
solicitado para ofrecer préstamos en euros utilizando BTC como colateral sin
custodia. El proyecto incluye contratos inteligentes, un backend mínimo de
orquestación y una interfaz web estática para operar los préstamos.

## Estructura del repositorio

- `contracts/` – Implementaciones Solidity para Avalanche y Ethereum, además de
  utilidades, interfaces y adaptadores de mensajería.
  - `ava/AvalancheLoanCoordinator.sol`: gestiona el depósito de BTC.b, acuña
    tokens de propiedad y coordina la mensajería cross-chain.
  - `eth/EthereumLoanCoordinator.sol`: administra la liberación de EURe,
    verifica repagos y ordena la liberación o liquidación del colateral.
  - `messaging/ChainlinkCCIPMessenger.sol`: adaptador listo para producción que
    conecta con Chainlink CCIP para enviar y recibir payloads entre redes.
  - `messaging/MockMessenger.sol`: mensajero ligero para pruebas locales.
- `backend/server.py` – Servidor HTTP de producción ligera (sin dependencias
  externas) que actúa como orquestador con integraciones a Monerium y
  Avalanche Bridge, almacenamiento persistente y monitorización de riesgo.
- `frontend/` – Aplicación web estática con simulador de LTV, seguimiento de
  préstamos y formularios de repago.
- `test/` – Suite de Foundry con mocks de dependencias externas y pruebas de
  los flujos clave del coordinador en Avalanche.

## Contratos inteligentes

Los contratos están escritos en Solidity ^0.8.20 y se diseñaron para ser
auto-contenidos, evitando dependencias externas. Para compilar y desplegar se
recomienda utilizar **Foundry** o **Hardhat** (añadiendo las dependencias
necesarias en tu entorno local). Las piezas clave son:

### `AvalancheLoanCoordinator`

- Recibe depósitos en BTC.b y los deposita en la vault gestionada de Silo
  Finance.
- Emite un token ERC‑20 (`OwnershipToken`) que prueba la titularidad del
  colateral.
- Calcula el principal en EUR aplicando el LTV solicitado (tope 70 %).
- Emite mensajes cross-chain mediante un mensajero genérico para que la parte en
  Ethereum libere los EURe.
- Gestiona el desbloqueo del colateral cuando recibe la confirmación de repago o
  ejecuta la liquidación en caso de impago.

### `EthereumLoanCoordinator`

- Registra nuevos préstamos tras recibir la notificación desde Avalanche.
- Entrega EURe al usuario (directamente o a una cuenta Monerium vinculada).
- Registra repagos, adjunta los parámetros necesarios para el bridge de vuelta
  a BTC y envía la orden de liberar el colateral.
- Permite marcar préstamos en default para iniciar la liquidación.

### Mensajería cross-chain

El contrato `ChainlinkCCIPMessenger` implementa la interfaz `ICrossChainMessenger`
utilizando Chainlink CCIP. Permite configurar el router, la dirección remota y
los parámetros de gas, además de validar el remitente de cada mensaje recibido
antes de reenviarlo a los contratos coordinadores. Para entornos puramente
locales sigue disponible `MockMessenger`.

## Backend

El backend en `backend/server.py` expone endpoints REST (`/loans`, `/repay`,
`/monerium/*`, `/bridge/*`, `/health`, `/metrics`, `/pricing/btc-eur`) protegidos
mediante API key opcional. Incluye clientes ligeros para Monerium (OAuth2 client
credentials) y para el Avalanche Bridge, almacén persistente basado en SQLite y
un monitor de riesgo en segundo plano que recalcula el LTV de cada préstamo y
emite eventos de alerta o default cuando los umbrales configurables se
superan.

Las respuestas de la API incluyen trazabilidad completa mediante el endpoint
`/loans/{id}/history`. El rate limiting integrado evita abusos, mientras que el
monitor automático permite detectar préstamos en riesgo y marcarlos como
`defaulted` sin intervención manual.

Para ejecutarlo:

```bash
python backend/server.py
```

Configura las siguientes variables de entorno para habilitar las integraciones
externas:

- `API_KEY`: valor compartido para autorizar peticiones.
- `MONERIUM_CLIENT_ID` y `MONERIUM_CLIENT_SECRET`: credenciales OAuth2.
- `MONERIUM_BASE_URL`: (opcional) apunta al entorno sandbox.
- `AVALANCHE_BRIDGE_URL`: (opcional) URL del bridge (por defecto la pública).
- `LOANSTORE_PATH`: (opcional) ruta de la base de datos SQLite para almacenar
  préstamos y eventos.
- `STATIC_BTC_EUR`: permite fijar un precio BTC/EUR (se prefiere dejarlo vacío
  para usar la cotización en vivo).
- `RATE_LIMIT` y `RATE_LIMIT_WINDOW`: controlan la política de rate limiting.
- `RISK_INTERVAL`: frecuencia en segundos del monitor de riesgo automático.

## Frontend

La carpeta `frontend/` contiene una SPA estática sin dependencias externas. Para
probarla basta con servirla con cualquier servidor estático, por ejemplo:

```bash
python -m http.server --directory frontend 9000
```

La aplicación permite:

- Conectar una wallet Web3 (utilizando `window.ethereum`).
- Consultar precios BTC/EUR en tiempo real y simular préstamos según el LTV
  deseado.
- Registrar préstamos y repagos consumiendo la API del backend protegido con
  API key.
- Visualizar métricas agregadas y el historial de eventos de cada préstamo.

## Pruebas automatizadas

La carpeta `test/` contiene una suite de Foundry con mocks de BTC.b, la vault de
Silo, el mensajero y el bridge. Para ejecutarla instala Foundry y lanza:

```bash
forge test
```

Esto valida la creación de préstamos, el flujo de repago y la ruta de
liquidación sobre el contrato `AvalancheLoanCoordinator`.

## Próximos pasos sugeridos

- Completar la configuración de CCIP con los IDs de cadena oficiales y cuentas
  con saldo de LINK para cubrir las tarifas en mainnet.
- Persistir el estado de `backend/server.py` en una base de datos externa y
  añadir colas de trabajo para reintentos (ej. Redis + RQ o Celery).
- Conectar la interfaz web con el backend reforzado, incluyendo autenticación
  multi-factor y paneles de auditoría en tiempo real.
