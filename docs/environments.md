# Guía de entornos

Esta guía describe los parámetros de infraestructura esperados para los entornos de **desarrollo**, **preproducción** y **producción**. Incluye las redes blockchain utilizadas, direcciones de contratos y configuraciones de backend conocidas. Todas las referencias deben verificarse con el equipo de **DevOps** y **Compliance** antes de cada despliegue.

## Resumen rápido

| Entorno | Redes previstas | Objetivo principal |
| --- | --- | --- |
| Desarrollo (`dev`) | Avalanche Fuji, Ethereum Sepolia | Pruebas funcionales integradas y validaciones de UI/backend sin riesgo financiero. |
| Preproducción (`preprod`) | Avalanche C-Chain (mainnet), Ethereum Mainnet (con límites de operación) | Ensayos finales con infraestructura real, límites de monto estrictos y mensajería CCIP en modo throttled. |
| Producción (`prod`) | Avalanche C-Chain, Ethereum Mainnet | Operación comercial con usuarios finales, límites regulados por Compliance y monitoreo 24/7. |

> **Recordatorio:** Antes de mover cambios entre entornos, confirmar que los parámetros coinciden con los registros vigentes en los gestores de secretos, archivos de infraestructura como código y contratos desplegados. Documentar cualquier desviación.

## Desarrollo (`dev`)

### Redes

| Recurso | Valor esperado | Notas |
| --- | --- | --- |
| Red Avalanche | Fuji Testnet (`chainId` 43113) | RPC público sugerido: `https://api.avax-test.network/ext/bc/C/rpc`. |
| Red Ethereum | Sepolia Testnet (`chainId` 11155111) | RPC público sugerido: `https://sepolia.infura.io/v3/<project>` o equivalente. |
| CCIP Chain IDs | Fuji ↔︎ Sepolia (IDs de prueba) | Confirmar con Chainlink el mapeo actualizado de `sourceChainSelector` y `destinationChainSelector`. |

### Direcciones de contratos y feeds

| Recurso | Identificador tentativo | Estado |
| --- | --- | --- |
| `AvalancheLoanCoordinator` | `0x????????????????????????????????????????` | Reemplazar con la dirección del despliegue más reciente en Fuji. |
| `EthereumLoanCoordinator` | `0x????????????????????????????????????????` | Reemplazar con la dirección del despliegue más reciente en Sepolia. |
| `ChainlinkCCIPMessenger` | `0x????????????????????????????????????????` | Debe estar configurado con los routers de prueba de CCIP. |
| Vault Silo BTC.b | `0x????????????????????????????????????????` | Utilizar la vault mock o la dirección oficial de Fuji si está disponible. |
| Feed BTC/USD (Chainlink) | `0x????????????????????????????????????????` | Tomar de la tabla oficial de Fuji. |
| Feed EUR/USD (Chainlink) | `0x????????????????????????????????????????` | Tomar de la tabla oficial de Fuji. |

> **Acción requerida:** Registrar las direcciones reales en este documento tras cada despliegue de contratos y compartir con DevOps para mantener sincronizados los archivos de configuración (por ejemplo, `foundry.toml`, variables del backend y manifiestos de infraestructura).

### Variables del backend

Configurar el backend con los siguientes valores de referencia (ajustar según el gestor de secretos utilizado):

| Variable | Valor dev sugerido | Comentario |
| --- | --- | --- |
| `AVALANCHE_RPC_URL` | `https://api.avax-test.network/ext/bc/C/rpc` | Preferir un endpoint dedicado si el tráfico supera el límite público. |
| `AVALANCHE_COORDINATOR_ADDRESS` | Dirección del despliegue en Fuji | Coincidir con la tabla de contratos. |
| `ETHEREUM_RPC_URL` | Endpoint Sepolia (Infura/Alchemy u otro) | Mantener la misma cuenta que usa el despliegue de contratos. |
| `ETHEREUM_COORDINATOR_ADDRESS` | Dirección del despliegue en Sepolia | Coincidir con la tabla de contratos. |
| `CHAINLINK_ROUTER_ADDRESS` | Router CCIP de pruebas | Confirmar con Chainlink el valor vigente para Fuji/Sepolia. |
| `MONERIUM_BASE_URL` | `https://api.sandbox.monerium.dev` | Sandbox obligatorio en dev. |
| `MONERIUM_CLIENT_ID` / `MONERIUM_CLIENT_SECRET` / `MONERIUM_SCOPE` | Credenciales sandbox | Gestionadas en el almacén de secretos `kv/dev/*`. |
| `AVALANCHE_BRIDGE_URL` | `https://staging-api.avax.network/bridge` | Usar el endpoint de pruebas del bridge. |
| `LOANSTORE_PATH` | `./data/loans-dev.sqlite` | Aislar datos por entorno. |
| `STATIC_BTC_EUR` | Opcional | Sólo para simulaciones cerradas. |

### Políticas operativas

- Utilizar **tokens de prueba** (`BTC.b` faucet, EURe de demostración, LINK de testnet) con cantidades limitadas.
- Límite de préstamo recomendado: ≤ 1000 EURe equivalentes por operación.
- Cuentas Monerium: usar únicamente credenciales de sandbox con IBAN virtuales de prueba.
- No reutilizar API keys ni secretos entre desarrolladores; cada persona debe solicitar sus credenciales.
- Registrar incidentes o valores atípicos en el canal `#ops-dev` para seguimiento.

## Preproducción (`preprod`)

### Redes

| Recurso | Valor esperado | Notas |
| --- | --- | --- |
| Red Avalanche | C-Chain Mainnet (`chainId` 43114) | RPC dedicado (por ejemplo, `https://api.avax.network/ext/bc/C/rpc`) con API key corporativa. |
| Red Ethereum | Mainnet (`chainId` 1) | RPC dedicado (Infura/Alchemy plan enterprise). |
| CCIP Chain IDs | Avalanche ↔︎ Ethereum (mainnet con throttling) | Activar rutas aprobadas por Chainlink con límites de gas reducidos. |

### Direcciones de contratos y feeds

| Recurso | Identificador tentativo | Estado |
| --- | --- | --- |
| `AvalancheLoanCoordinator` | `0x????????????????????????????????????????` | Versión candidata a producción desplegada en mainnet. |
| `EthereumLoanCoordinator` | `0x????????????????????????????????????????` | Mantener sincronizado con la versión de producción. |
| `ChainlinkCCIPMessenger` | `0x????????????????????????????????????????` | Configurar con el router CCIP principal en modo throttled. |
| Vault Silo BTC.b | Dirección oficial en Avalanche | Confirmar con Silo Finance la vault activa para BTC.b. |
| Feed BTC/USD (Chainlink) | Dirección oficial en Avalanche mainnet | Obtener de la documentación de Chainlink. |
| Feed EUR/USD (Chainlink) | Dirección oficial en Avalanche mainnet | Obtener de la documentación de Chainlink. |
| Feed BTC/EUR (Chainlink) | Dirección oficial en Ethereum mainnet | Utilizado como referencia cruzada en el oráculo. |

### Variables del backend

| Variable | Valor preprod sugerido | Comentario |
| --- | --- | --- |
| `AVALANCHE_RPC_URL` | Endpoint corporativo mainnet | Requiere autenticación mediante token/API key. |
| `AVALANCHE_COORDINATOR_ADDRESS` | Dirección desplegada en mainnet (preprod) | Validar con contratos. |
| `ETHEREUM_RPC_URL` | Endpoint corporativo mainnet | Compartido con pipelines de despliegue. |
| `ETHEREUM_COORDINATOR_ADDRESS` | Dirección desplegada en mainnet (preprod) | Validar con contratos. |
| `CHAINLINK_ROUTER_ADDRESS` | Router CCIP mainnet | Confirmar con Chainlink. |
| `MONERIUM_BASE_URL` | `https://api.sandbox.monerium.dev` | Mantener sandbox hasta aprobación de Compliance. |
| `MONERIUM_CLIENT_ID` / `MONERIUM_CLIENT_SECRET` / `MONERIUM_SCOPE` | Credenciales sandbox segregadas | Gestionar en `kv/preprod/*`. |
| `AVALANCHE_BRIDGE_URL` | `https://api.avax.network/bridge` | Endpoint principal con restricciones de monto. |
| `RATE_LIMIT` / `RATE_LIMIT_WINDOW` | Valores acordados con Ops | Configurar en el despliegue (ej. 60 req/min). |
| `LOANSTORE_PATH` | `./data/loans-preprod.sqlite` | Puede migrarse a base externa si se replica producción. |

### Políticas operativas

- **Tokens:** utilizar BTC.b real con montos limitados y EURe emitido en contenedores controlados (devolver al finalizar las pruebas).
- **Límites de monto:** tope recomendado 5 000 € por préstamo y 15 000 € agregados diarios.
- **Mensajería CCIP:** habilitar modo rate-limited y monitorear costos de LINK; recargar desde la tesorería de pruebas.
- **Monerium:** mantener cuentas sandbox; no usar IBAN de clientes reales. Requiere lista blanca de IBAN internos.
- **Auditoría:** registrar cada despliegue o cambio de parámetros en el runbook de cambios (`docs/runbooks/`).

## Producción (`prod`)

### Redes

| Recurso | Valor esperado | Notas |
| --- | --- | --- |
| Red Avalanche | C-Chain Mainnet (`chainId` 43114) | RPC dedicado con SLA 99.9 %, redundancia multi-proveedor. |
| Red Ethereum | Mainnet (`chainId` 1) | RPC dedicado con failover; considerar nodos propios como respaldo. |
| CCIP Chain IDs | Avalanche ↔︎ Ethereum (mainnet) | Rutas aprobadas con cuotas suficientes para el volumen esperado. |

### Direcciones de contratos y feeds

| Recurso | Identificador tentativo | Estado |
| --- | --- | --- |
| `AvalancheLoanCoordinator` | `0x????????????????????????????????????????` | Dirección oficial firmada por el multi-sig de operaciones. |
| `EthereumLoanCoordinator` | `0x????????????????????????????????????????` | Debe coincidir con la versión auditada. |
| `ChainlinkCCIPMessenger` | `0x????????????????????????????????????????` | Configurado con límites de gas y tarifas aprobados. |
| Vault Silo BTC.b | Dirección oficial en Avalanche | Confirmar con Silo Finance y monitorear TVL. |
| Feed BTC/USD (Chainlink) | Dirección oficial en Avalanche mainnet | Registrar revisiones periódicas. |
| Feed EUR/USD (Chainlink) | Dirección oficial en Avalanche mainnet | Registrar revisiones periódicas. |
| Feed BTC/EUR (Chainlink) | Dirección oficial en Ethereum mainnet | Auditoría semestral recomendada. |

### Variables del backend

| Variable | Valor producción sugerido | Comentario |
| --- | --- | --- |
| `AVALANCHE_RPC_URL` | Endpoint principal + fallback | Documentar ambos en Vault `kv/prod/avalanche-rpc`. |
| `AVALANCHE_COORDINATOR_ADDRESS` | Dirección oficial firmada | No modificar sin aprobación del comité de cambios. |
| `ETHEREUM_RPC_URL` | Endpoint principal + fallback | Documentar ambos en Vault `kv/prod/ethereum-rpc`. |
| `ETHEREUM_COORDINATOR_ADDRESS` | Dirección oficial firmada | Requiere control de cambios. |
| `CHAINLINK_ROUTER_ADDRESS` | Router CCIP mainnet | Alinear con el contrato auditado. |
| `MONERIUM_BASE_URL` | `https://api.monerium.app` | Producción; requiere credenciales separadas. |
| `MONERIUM_CLIENT_ID` / `MONERIUM_CLIENT_SECRET` / `MONERIUM_SCOPE` | Credenciales de producción | Gestionadas en `kv/prod/*`, rotación trimestral. |
| `API_KEY` | API key pública/privada para clientes | Rotación mensual mínima. |
| `AVALANCHE_OPERATOR_KEY` / `ETHEREUM_OPERATOR_KEY` | Claves de firma operativa | Custodia en HSM; nunca exponer en archivos planos. |
| `RATE_LIMIT` / `RATE_LIMIT_WINDOW` | Definidos por Compliance | Ej. 30 req/min por IP. |
| `RISK_INTERVAL` | ≤ 300 segundos | Ajustar según SLA de monitoreo. |
| `LOANSTORE_PATH` | Backend conectado a base gestionada | Reemplazar por `DATABASE_URL` si se migra a PostgreSQL. |

### Políticas operativas

- **Tokens y liquidez:** operaciones con activos reales; coordinar recargas de BTC.b, EURe y LINK con tesorería.
- **Límites de monto:** sujetos a las políticas de Compliance; documentar los límites vigentes (ej. 50 000 € por préstamo, 250 000 € diarios).
- **Monerium:** usar cuentas de producción autorizadas; activar monitoreo de transacciones sospechosas y reportes AML.
- **Seguridad:** todas las modificaciones requieren aprobación del comité de cambios y registro en el sistema GRC.
- **Monitoreo:** habilitar alertas en Prometheus/Grafana y logs centralizados; notificar a on-call ante fallos de CCIP o diferencias de oráculo.

## Procedimiento de validación con DevOps y Compliance

1. **Consolidar parámetros:** preparar un resumen con los valores propuestos para redes, direcciones de contratos, variables del backend y políticas de operación del entorno que se va a desplegar.
2. **Revisión de DevOps:** validar que los endpoints RPC, routers CCIP, feeds y direcciones de contratos existan en los registros de infraestructura (Terraform/Helm, gestores de secretos, pipelines de CI/CD).
3. **Revisión de Compliance:** confirmar que los límites de montos, uso de tokens y cuentas Monerium cumplen las políticas vigentes y las licencias disponibles.
4. **Aprobación documentada:** registrar en la herramienta corporativa (por ejemplo, Jira/ServiceNow) la aprobación con fecha, responsables y enlaces a los artefactos actualizados.
5. **Despliegue controlado:** una vez aprobados los parámetros, ejecutar el despliegue siguiendo el runbook correspondiente y adjuntar evidencia de validación (capturas, hashes de contratos, comprobantes de configuración).

Mantener esta guía actualizada tras cualquier cambio en la infraestructura, componentes externos o políticas regulatorias.
