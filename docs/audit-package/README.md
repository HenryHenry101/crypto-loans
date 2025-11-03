# Paquete de Documentación para Auditoría

Este paquete recopila la información mínima necesaria para que proveedores de
auditoría evalúen los contratos inteligentes y el backend regulado de Crypto
Loans.

## Contenido

- `architecture.md`: descripción de la arquitectura on-chain/off-chain y
  dependencias críticas.
- `integration-diagrams.md`: diagramas Mermaid de los flujos de originación,
  repago y liquidación con Monerium y Avalanche Bridge.
- `abi/`: ABIs actualizadas de los coordinadores de préstamo en Avalanche y
  Ethereum (extraídas de `backend/abi/`).
- `rfp.md`: solicitud de propuestas con alcance detallado y ventana de ejecución
  esperada.
- `timeline.md`: cronograma interno con hitos, responsables y métricas de
  seguimiento.

## Instrucciones para firmas auditoras

1. Solicitar acceso al repositorio privado y a los entornos de staging descritos
   en `rfp.md`.
2. Revisar `architecture.md` y los contratos en `contracts/` para comprender las
   responsabilidades de cada componente.
3. Consultar los ABIs en `abi/` para integrar herramientas de análisis o fuzzing.
4. Utilizar los diagramas de `integration-diagrams.md` para validar supuestos de
   mensajería y dependencias externas.
5. Entregar la propuesta antes del **7 de marzo de 2025** siguiendo las pautas
   del RFP.

Para dudas adicionales contactar al equipo interno a través de los canales
indicados en `timeline.md`.
