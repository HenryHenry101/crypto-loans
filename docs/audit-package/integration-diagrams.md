# Diagramas de Integración

Los siguientes diagramas describen los flujos entre contratos, backend y los
servicios externos (Monerium y Avalanche Bridge) relevantes para la auditoría.

## Flujo de originación de préstamo

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant Backend
    participant Avalanche as Avalanche Loan Coordinator
    participant CCIP as Chainlink CCIP
    participant Ethereum as Ethereum Loan Coordinator
    participant Monerium

    User->>Frontend: Solicita préstamo (monto, LTV)
    Frontend->>Backend: POST /loans (payload firmado)
    Backend->>Avalanche: depositCollateral(amountBTCb)
    Avalanche-->>Backend: Evento CollateralDeposited
    Avalanche->>CCIP: Enviar mensaje loanInitiated
    CCIP->>Ethereum: deliverMessage(payload)
    Ethereum->>Backend: webhook/emit LoanRegistered
    Backend->>Monerium: POST /transactions (emitir EURe)
    Monerium-->>Backend: Confirmación emisión
    Backend-->>User: Notificación de disponibilidad EURe
```

## Flujo de repago

```mermaid
sequenceDiagram
    participant User
    participant Monerium
    participant Backend
    participant Ethereum as Ethereum Loan Coordinator
    participant CCIP as Chainlink CCIP
    participant Avalanche as Avalanche Loan Coordinator

    User->>Monerium: Transferencia EURe de repago
    Monerium->>Backend: Webhook transacción recibida
    Backend->>Ethereum: POST /repay (loanId, amount)
    Ethereum->>CCIP: Enviar mensaje releaseCollateral
    CCIP->>Avalanche: deliverMessage(payload)
    Avalanche->>Backend: releaseCollateral(loanId)
    Backend-->>User: Confirmación de devolución BTC.b / prueba de bridge
```

## Flujo de liquidación

```mermaid
sequenceDiagram
    participant Risk as Monitor de Riesgo
    participant Backend
    participant Avalanche as Avalanche Loan Coordinator
    participant DEX
    participant Bridge as Avalanche Bridge
    participant User

    Risk->>Backend: Evento loanAtRisk(default)
    Backend->>Avalanche: liquidate(loanId)
    Avalanche->>DEX: Swap BTC.b → EURe (según slippage)
    Avalanche->>Bridge: Initiate bridge back to BTC
    Bridge-->>Backend: Proof hash / estado
    Backend-->>User: Reporte de liquidación
```

Estos diagramas se basan en la implementación actual y deben validarse contra
las pruebas automatizadas y configuraciones de despliegue antes de la auditoría.
