```mermaid
flowchart TD
    A[Lead JSON Input] --> B[Python Field Cleaning]
    B --> C[Required Field Validation]

    C --> D{Is lead valid?}

    D -- No --> E[Mark as Invalid]
    E --> F[Save error_reason]
    F --> G[Write Error Log]

    D -- Yes --> H[Send to n8n Webhook]
    H --> I[AI Lead Analysis]

    I --> J[Classify lead_type]
    J --> K[Classify b2b_category]
    K --> L[Classify intent_level]
    L --> M[Generate lead_score]
    M --> N[Generate lead_summary]
    N --> O[Generate recommended_action]
    O --> P[Generate follow_up_email]

    P --> Q[Map Fields to CRM Schema]
    Q --> R[Write to Notion / Airtable CRM]

    R --> S{High-intent B2B lead?}

    S -- Yes --> T[Send Human Review Notification]
    S -- No --> U[No Priority Notification]

    T --> V[Save Processing Log]
    U --> V[Save Processing Log]
