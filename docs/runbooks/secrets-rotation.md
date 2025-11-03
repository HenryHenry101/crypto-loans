# Runbook de rotación de secretos

Este runbook describe el procedimiento para rotar los secretos del backend de
Crypto Loans manteniendo el principio de mínimo privilegio. Aplica a los entornos
de **desarrollo**, **preproducción** y **producción**.

## Roles y controles de acceso

- **Propietario del secreto:** líder de plataforma responsable de crear y rotar
  el secreto en el gestor corporativo.
- **Consumidor del secreto:** pipeline o servicio que necesita leer el valor.
- **Auditor:** responsable de seguridad que valida la rotación y revisa logs.

Los accesos al gestor de secretos deben otorgarse mediante políticas dedicadas:

- `secret-reader-<entorno>`: lectura para los servicios que inyectan variables en
  tiempo de despliegue.
- `secret-writer-<entorno>`: escritura y rotación disponible únicamente para el
  propietario del secreto.
- Revocar accesos temporales una vez completada la rotación.

## Procedimiento general

1. **Programar ventana de mantenimiento** con los equipos de backend y
   operaciones.
2. **Generar el nuevo valor** del secreto siguiendo las guías del proveedor:
   - `API_KEY`: generar token aleatorio de al menos 32 bytes (ej. `openssl rand -hex 32`).
   - `MONERIUM_CLIENT_ID` / `MONERIUM_CLIENT_SECRET`: crear nuevo par OAuth2 en
     el panel de Monerium.
   - `MONERIUM_SCOPE`: confirmar los scopes mínimos necesarios y actualizarlos
     si Monerium introduce cambios.
   - `STATIC_BTC_EUR`: establecer nuevo valor sólo si se utiliza el modo estático.
3. **Registrar el nuevo valor** en el gestor de secretos dentro de la ruta
   correspondiente (`kv/<entorno>/<secreto>`).
4. **Actualizar los pipelines**:
   - Verificar que los pipelines referencian el secreto mediante variables
     inyectadas (ej. `vault kv get` → export en tiempo de ejecución).
   - Evitar imprimir los valores en los logs (`set +x` en scripts bash, variables
     marcadas como secretas en el runner).
5. **Desplegar el backend** apuntando al nuevo secreto:
   - Forzar redeploy/rolling restart para que el proceso lea las variables
     actualizadas.
   - Confirmar en los logs de arranque que se detectan los nuevos valores sin
     exponerlos.
6. **Validar funcionamiento**:
   - Ejecutar pruebas de API (creación de préstamo, integración con Monerium).
   - Revisar métricas y alertas.
7. **Revocar credenciales antiguas**:
   - Eliminar `API_KEY` viejo de cualquier gestor temporal.
   - Invalidar el client secret previo en Monerium.
8. **Actualizar inventario** (`docs/secret-inventory.md`) con fecha de rotación,
   responsable y enlace a la evidencia.
9. **Cierre y auditoría**:
   - Auditor confirma que el secreto nuevo funciona y que no hay accesos
     adicionales en las políticas.
   - Archivar comprobantes en la herramienta de seguimiento corporativa.

## Frecuencia recomendada

- `API_KEY`: rotación cada 90 días o ante incidentes.
- Credenciales de Monerium: seguir las políticas del proveedor, mínimo cada 180
  días.
- Otros valores: rotar cuando cambie el contexto operativo.

## Validaciones posteriores

- Revisar las políticas de acceso en el gestor de secretos para garantizar que
  únicamente los servicios/pipelines esperados tienen permisos de lectura.
- Ejecutar `terraform plan` o herramienta equivalente para confirmar que no se
  introdujeron credenciales estáticas en la infraestructura.
- Registrar en el sistema de tickets el cierre de la actividad con referencias a
  los commits y despliegues relacionados.
