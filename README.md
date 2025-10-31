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
- `backend/server.py` – Servidor HTTP ligero (sin dependencias externas) que
  actúa como orquestador demostrativo con integraciones a Monerium y Avalanche
  Bridge.
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
- Registra repagos y envía la orden de liberar el colateral.
- Permite marcar préstamos en default para iniciar la liquidación.

### Mensajería cross-chain

El contrato `ChainlinkCCIPMessenger` implementa la interfaz `ICrossChainMessenger`
utilizando Chainlink CCIP. Permite configurar el router, la dirección remota y
los parámetros de gas, además de validar el remitente de cada mensaje recibido
antes de reenviarlo a los contratos coordinadores. Para entornos puramente
locales sigue disponible `MockMessenger`.

## Backend

El backend en `backend/server.py` expone endpoints REST (`/loans`, `/repay`,
`/monerium/*`, `/bridge/*`, `/health`) protegidos mediante API key opcional.
Incluye clientes ligeros para Monerium (OAuth2 client credentials) y para el
Avalanche Bridge, además de un almacén en memoria con trazabilidad de eventos
de cada préstamo. Su objetivo sigue siendo actuar como blueprint de referencia
para migrar posteriormente a un framework robusto (FastAPI, NestJS).

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

## Frontend

La carpeta `frontend/` contiene una SPA estática sin dependencias externas. Para
probarla basta con servirla con cualquier servidor estático, por ejemplo:

```bash
python -m http.server --directory frontend 9000
```

La aplicación permite:

- Conectar una wallet Web3 (utilizando `window.ethereum`).
- Simular préstamos en función del LTV.
- Listar préstamos activos y lanzar el flujo de repago.

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
