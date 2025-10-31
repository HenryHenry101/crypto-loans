# Crypto Loans – Plataforma de préstamos con BTC como colateral

Este repositorio contiene una implementación de referencia basada en el blueprint
solicitado para ofrecer préstamos en euros utilizando BTC como colateral sin
custodia. El proyecto incluye contratos inteligentes, un backend mínimo de
orquestación y una interfaz web estática para operar los préstamos.

## Estructura del repositorio

- `contracts/` – Implementaciones Solidity para Avalanche y Ethereum, además de
  utilidades, interfaces y un mensajero de ejemplo.
  - `ava/AvalancheLoanCoordinator.sol`: gestiona el depósito de BTC.b, acuña
    tokens de propiedad y coordina la mensajería cross-chain.
  - `eth/EthereumLoanCoordinator.sol`: administra la liberación de EURe,
    verifica repagos y ordena la liberación o liquidación del colateral.
  - `messaging/MockMessenger.sol`: mensajero de ejemplo para entornos de
    desarrollo.
- `backend/server.py` – Servidor HTTP ligero (sin dependencias externas) que
  actúa como orquestador demostrativo.
- `frontend/` – Aplicación web estática con simulador de LTV, seguimiento de
  préstamos y formularios de repago.

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

El contrato `MockMessenger` ilustra cómo integrar un protocolo como Chainlink
CCIP o LayerZero. En producción se debe sustituir por la implementación oficial
del proveedor elegido.

## Backend

El backend en `backend/server.py` ofrece endpoints REST muy básicos (`/loans`,
`/repay`, `/health`) para integrar wallets, Monerium y la capa de mensajería. El
objetivo es mostrar el flujo de datos y servir de punto de partida para una
implementación completa en un framework robusto.

Para ejecutarlo:

```bash
python backend/server.py
```

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

## Próximos pasos sugeridos

- Sustituir `MockMessenger` por el adaptador real del protocolo cross-chain
  elegido.
- Añadir pruebas automatizadas con Foundry o Hardhat.
- Completar la integración con la API de Monerium y el bridge oficial de
  Avalanche para mover BTC ↔ BTC.b.
- Incorporar autenticación y controles de seguridad en el backend.
