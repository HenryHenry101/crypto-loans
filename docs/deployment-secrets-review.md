# Revisión de consumo de secretos en despliegues

Durante la auditoría del repositorio no se encontraron pipelines CI/CD ni scripts
de despliegue (`.github/workflows`, `deploy/*.sh`, `Makefile`, etc.). Esto indica
que la inyección de secretos ocurre fuera de este repositorio (por ejemplo en un
repositorio de infraestructura o en la plataforma de CI corporativa).

## Acciones recomendadas

1. **Verificar los pipelines existentes** en la plataforma corporativa:
   - Confirmar que cada job obtiene las variables sensibles desde el gestor de
     secretos (`vault`, `secrets manager`, etc.) mediante credenciales de corto
     plazo.
   - Asegurar que los valores se exportan a variables de entorno justo antes de
     ejecutar el backend y que nunca se imprimen en los logs.
2. **Eliminar credenciales incrustadas**:
   - Revisar los repositorios de infraestructura o scripts heredados para
     detectar valores codificados.
   - Configurar mascarado de logs en runners (`::add-mask::` en GitHub Actions,
     `secrets` en GitLab CI, etc.).
3. **Agregar validaciones automáticas**:
   - Linters que detecten patrones de secretos (`trufflehog`, `gitleaks`).
   - Política de revisión que impida merges sin referencia al inventario de
     secretos.
4. **Documentar el flujo de inyección** en los repositorios correspondientes y
   enlazar a este archivo desde la documentación de la plataforma.

> En caso de que se creen pipelines específicos para este repositorio, incluir un
> paso explícito que lea los secretos definidos en `docs/secret-inventory.md` y
> mantenga el log en modo silencioso (`set +x`).
