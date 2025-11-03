# Guía de Onboarding de Usuarios

> **Validación de cumplimiento**: El equipo de Producto y Compliance revisó este flujo el 2024-05-07 y confirmó que los textos incluyen las advertencias legales, consentimientos AML/KYC y recordatorios de riesgo exigidos por la política interna.

## Cuenta Monerium

1. **Crear la cuenta y registrar el IBAN europeo**
   - Accede al panel de Monerium y solicita un IBAN SEPA individual. El proceso requiere documentación de identidad válida, prueba de residencia y declaración de origen de fondos.
   - Mantén disponible la confirmación oficial del IBAN: el formulario `#moneriumSection` de la interfaz exige introducir el IBAN exactamente como lo valida Monerium (`frontend/index.html`).
2. **Completar verificaciones KYC/AML**
   - Monerium solicita verificaciones de conocimiento del cliente y anti-blanqueo. Asegúrate de cargar la documentación y contestar los cuestionarios dentro de los plazos establecidos; sin esta aprobación, las transferencias EURe → IBAN quedan bloqueadas.
   - Guarda la constancia de aprobación: el equipo de Compliance puede requerirla para auditorías posteriores.
3. **Vincular la wallet ERC-20**
   - Conecta tu wallet (MetaMask/Core/EVM compatible) en la dApp y navega hasta el formulario `#moneriumSection`.
   - El botón **“Firmar y vincular”** ejecuta `handleMoneriumLink` (`frontend/js/app.js`), que genera un mensaje con el IBAN, la wallet y una marca de tiempo, y solicita tu firma EIP-191.
   - Tras firmar, el backend almacena el hash del mensaje, la firma y el `moneriumUserId`, vinculando de forma persistente la cuenta. Revisa la alerta verde con el hash abreviado para confirmar.
4. **Advertencias legales**
   - Al vincular Monerium aceptas compartir datos personales con el proveedor regulado y autorizar comprobaciones continuas AML/KYC.
   - Cualquier discrepancia en el IBAN o titularidad detiene los desembolsos; la remediación requiere presentar documentación adicional a Compliance.

## Wallet BTC compatible con Avalanche Bridge

1. **Instalación y configuración (ejemplo: Core Wallet)**
   - Descarga [Core Wallet](https://core.app/) para escritorio o navegador y sigue el asistente para crear/recuperar tu wallet.
   - Activa la compatibilidad con Avalanche C-Chain y habilita el módulo “Bitcoin” para gestionar direcciones SegWit (bc1…).
   - Respalda la seed phrase en un medio seguro; no la compartas con terceros.
2. **Requisitos antes de usar el bridge**
   - Para el formulario `bridgeWrapForm`, envía BTC a tu dirección Core y espera **al menos 6 confirmaciones** en Bitcoin antes de introducir el hash en la dApp. Esto reduce el riesgo de reorganizaciones y cumple las políticas antifraude.
   - Para `bridgeUnwrapForm`, asegúrate de que el saldo BTC.b en Avalanche haya confirmado en la C-Chain (≥1 bloque) y que la dirección BTC destino soporte SegWit nativo.
   - Mantén liquidez suficiente en AVAX para cubrir comisiones cuando el backend ejecute transacciones en Avalanche.
3. **Buenas prácticas de cumplimiento**
   - Verifica que las direcciones utilizadas pertenezcan a ti y no estén listadas en reportes de sanciones. El equipo de Compliance puede bloquear operaciones si detecta coincidencias.
   - Conserva los comprobantes de cada wrap/unwrap (ID del bridge y hashes on-chain) para cumplir con solicitudes regulatorias.

## Firma de términos y condiciones

1. **Uso del simulador de préstamo**
   - En la sección “Simulador de préstamo” ajusta el monto en EUR, el LTV y la duración para visualizar el colateral requerido. La app consulta precios en tiempo real y previene LTV superiores al 70%.
   - Selecciona el método de desembolso (wallet o Monerium) y completa campos opcionales como referencia de transferencia, siguiendo la política de transparencia.
2. **Aceptar y firmar los T&C**
   - Lee el bloque de Términos y Condiciones y marca la casilla de aceptación. Esto habilita el botón `#signTermsButton`.
   - Al pulsar “Firmar aceptación T&C”, la lógica `handleTermsSignature` (`frontend/js/app.js`) genera un payload EIP-712 con tu wallet, el hash canónico (`TERMS_HASH`) y un timestamp.
   - La firma se almacena en memoria local hasta que se envía una solicitud de préstamo; el backend verifica que el hash coincida, guarda la firma y registra el evento `terms-accepted` junto con la versión vigente.
3. **Custodia del hash y la firma**
   - El backend persiste `termsHash`, `termsSignature` y la marca temporal (`accepted_at`) en su almacén SQLite, vinculados a tu wallet, para demostrar consentimiento informado ante auditorías.
   - Si se actualiza la versión de términos (`TERMS_VERSION`), se solicitará una nueva firma. El historial previo se conserva para trazabilidad.
4. **Advertencias legales**
   - Firmar los T&C implica aceptar liquidaciones automáticas y reportes regulatorios derivados de AML/KYC.
   - Operar el simulador no crea obligaciones financieras hasta que envías la transacción on-chain, pero sí habilita el tratamiento de tus datos conforme a la política de privacidad.

---

Para dudas adicionales, contacta a Producto (`producto@crypto-loans.example`) o Compliance (`compliance@crypto-loans.example`).
