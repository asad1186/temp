Here is a sample flowchart:

```mermaid
flowchart TD
    A[Start] --> B{Decision};
    B --> C{Decision 2};
C --> D[Result 1];
C --> E[Result 2];
    B --> D;
    D & E --> F[End];
