# Inventario de secretos y variables sensibles

Este documento consolida las variables de entorno descritas en el `README.md` y
el uso observado en el código del backend. Sirve como punto de partida para
crear las entradas necesarias en los gestores de secretos de los entornos de
**desarrollo**, **preproducción** y **producción**.

## Variables detectadas

| Variable | Descripción | Componente | Requiere secreto | Notas de gestor de secretos |
| --- | --- | --- | --- | --- |
| `API_KEY` | Llave compartida para autorizar peticiones entrantes al backend. | `backend/server.py` | Sí | 🔴 **Pendiente**: no se identificaron entradas en los gestores de secretos. Crear en `kv/dev/api-key`, `kv/preprod/api-key` y `kv/prod/api-key` o ruta equivalente. |
| `MONERIUM_CLIENT_ID` | Credencial OAuth2 para integrar con Monerium. | `backend/server.py` | Sí | 🔴 **Pendiente**: crear secretos `kv/*/monerium-client-id`. |
| `MONERIUM_CLIENT_SECRET` | Secreto OAuth2 de Monerium. | `backend/server.py` | Sí | 🔴 **Pendiente**: crear secretos `kv/*/monerium-client-secret`. |
| `MONERIUM_BASE_URL` | URL del entorno de Monerium (sandbox o producción). | `backend/server.py` | No (valor configurable) | 🟡 Opcional: parametrizar mediante secreto únicamente si se requiere diferenciar entornos. |
| `MONERIUM_SCOPE` | Alcance OAuth2 solicitado al token de Monerium. | `backend/server.py` | Sí | 🔴 **Pendiente**: crear secretos `kv/*/monerium-scope`. |
| `AVALANCHE_BRIDGE_URL` | Endpoint para el Avalanche Bridge. | `backend/server.py` | No (valor público) | 🟡 Mantener como variable configurable sin secreto salvo que se utilice una instancia privada. |
| `LOANSTORE_PATH` | Ruta del archivo SQLite con el histórico de préstamos. | `backend/server.py` | No | 🟡 Definir como variable de entorno en los despliegues; no requiere secreto. |
| `STATIC_BTC_EUR` | Precio fijo BTC/EUR para pruebas. | `backend/server.py` | Sí (si se usa para simulaciones cerradas) | 🟢 Crear secretos `kv/*/static-btc-eur` sólo cuando se necesite fijar el precio. |
| `RATE_LIMIT` | Número de solicitudes permitidas. | `backend/server.py` | No | ⚪ Configurar en el manifiesto/helm chart o pipeline. |
| `RATE_LIMIT_WINDOW` | Ventana temporal del rate limit. | `backend/server.py` | No | ⚪ Configurar en el manifiesto/helm chart o pipeline. |
| `RISK_INTERVAL` | Frecuencia del monitor de riesgo automático. | `backend/server.py` | No | ⚪ Configurar en el manifiesto/helm chart o pipeline. |

> **Nota:** No se encontraron scripts ni definiciones de pipelines en el
> repositorio que administren estos valores. Durante la auditoría no se pudo
> comprobar la existencia de entradas reales en los gestores de secretos de los
> entornos. Es necesario crear o validar dichas entradas manualmente y registrar
> el estado en esta tabla.

## Acciones recomendadas

1. Coordinar con los responsables de plataforma para crear las entradas en los
   gestores de secretos (`HashiCorp Vault`, `AWS Secrets Manager`, `Azure Key
   Vault`, etc.) siguiendo el esquema `kv/<entorno>/<nombre>` propuesto o el
   estándar corporativo.
2. Registrar en esta tabla la fecha de creación/actualización y el responsable
   una vez completada la carga de cada secreto.
3. Configurar los despliegues para inyectar los valores a través de variables de
   entorno sin exponerlos en archivos de configuración ni registros.
