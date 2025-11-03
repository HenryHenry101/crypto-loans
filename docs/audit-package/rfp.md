# Solicitud de Propuestas (RFP) – Auditoría Integral Crypto Loans

## Objetivo

Contratar una firma de auditoría especializada para revisar los componentes on-chain
(Solidity, mensajería cross-chain, oráculos) y el backend regulado responsable de
integrarse con Monerium y Avalanche Bridge.

## Alcance técnico

1. **Contratos Solidity**
   - `contracts/ava/` (coordinador Avalanche, adapter de bridge, tokens auxiliares).
   - `contracts/eth/` (coordinador Ethereum, oráculo, utilidades comunes).
   - `contracts/messaging/ChainlinkCCIPMessenger.sol` y `contracts/oracles/ChainlinkPriceOracle.sol`.
   - Revisión de librerías internas (`contracts/libs/*.sol`) utilizadas por ambos coordinadores.

2. **Mensajería y oráculos**
   - Validación de payloads CCIP, verificación de remitentes, gestión de reintentos.
   - Confirmación de límites y freshness en `ChainlinkPriceOracle`.

3. **Backend regulado (`backend/`)**
   - API REST (`/loans`, `/repay`, `/monerium/*`, `/bridge/*`, `/metrics`).
   - Módulos de integración Monerium (OAuth2, webhooks) y Avalanche Bridge.
   - Monitor de riesgo automático, controles de acceso (API Key, rate limiting) y persistencia SQLite.

4. **Integración Monerium**
   - Validación de flujos de emisión/redención EURe descritos en `docs/audit-package/integration-diagrams.md`.
   - Revisión de manejo de datos personales y cumplimiento KYC/AML delegado en el backend.

## Entregables requeridos

- Informe inicial con hallazgos categorizados (Critical/High/Medium/Low/Informational).
- Recomendaciones de remediación priorizadas con estimación de esfuerzo.
- Sesión de walkthrough con el equipo interno para revisar hallazgos críticos.
- Informe de verificación posterior a correcciones.

## Ventana de ejecución

- **Kick-off:** Semana del 17 de marzo de 2025.
- **Auditoría on-chain:** 17 de marzo – 4 de abril (3 semanas).
- **Auditoría backend/integraciones:** 31 de marzo – 11 de abril (2 semanas solapadas).
- **Entrega de reporte inicial:** 14 de abril de 2025.
- **Revisión de fixes y validación final:** 21 – 30 de abril de 2025.

## Información adicional

- Repositorio privado disponible bajo NDA (GitHub, acceso read-only).
- Documentación de arquitectura y ABIs incluida en `docs/audit-package/`.
- Expectativa de comunicación asíncrona vía Slack dedicado + reuniones semanales.

Las firmas interesadas deben enviar su propuesta con experiencia relevante, equipo
asignado, metodología y presupuesto estimado antes del **7 de marzo de 2025**.
