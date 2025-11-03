# Cronograma y Responsables Internos

El siguiente cronograma define las etapas clave de la auditoría, responsables
internos y entregables asociados.

| Hito | Fecha | Responsable interno | Descripción |
|------|-------|--------------------|-------------|
| Preparación de auditoría | 3 – 14 marzo 2025 | CTO (Laura Gómez) + Lead Solidity (Andrés Silva) | Congelar rama `audit/2025`, validar despliegues de prueba, compartir documentación `docs/audit-package/`. |
| Kick-off con firma seleccionada | 17 marzo 2025 | CTO + Compliance Officer (María Ruiz) | Reunión inicial, revisión de agenda, acuerdos de comunicación y acceso a repositorio. |
| Auditoría on-chain (Solidity + CCIP) | 17 marzo – 4 abril 2025 | Lead Solidity (Andrés Silva) | Soporte técnico para dudas sobre coordinadores, oráculos y bridge adapter; respuesta ≤24h. |
| Auditoría backend/integraciones | 31 marzo – 11 abril 2025 | Lead Backend (Carlos Méndez) | Proporcionar acceso a ambientes de staging, documentación Monerium y colecciones API. |
| Entrega de reporte inicial | 14 abril 2025 | CTO | Recepción formal de hallazgos, distribución interna, programación de sesión de walkthrough. |
| Remediación prioritaria | 15 – 24 abril 2025 | Equipos Solidity y Backend | Implementar fixes según criticidad, actualizar pruebas (`forge test`, pruebas unitarias backend). |
| Validación post-fixes | 21 – 30 abril 2025 | QA Lead (Sofía Herrera) | Coordinar con firma auditora retest de hallazgos críticos/altos, recopilar evidencia de verificación. |
| Cierre de auditoría | 2 mayo 2025 | CTO + Compliance Officer | Firmar informe final, actualizar runbooks y registrar lecciones aprendidas. |

## Canales de comunicación

- **Slack #audit-2025**: coordinación diaria y seguimiento de tareas.
- **Email**: auditoria@crypto-loans.xyz para notificaciones formales.
- **Gestión de issues**: GitHub Projects “Audit 2025” con tableros por severidad.

## Métricas de seguimiento

- Tiempo medio de respuesta a consultas de auditoría (< 12h).
- Porcentaje de hallazgos críticos resueltos dentro del SLA (100% en ≤5 días).
- Cobertura de pruebas post-remediación (`forge test`, `pytest backend/tests`) = 100% éxito.
