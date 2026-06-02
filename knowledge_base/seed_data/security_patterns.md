# Security Patterns

## Authentication and Authorization Patterns

JWT (JSON Web Tokens) for stateless API authentication: the server issues a signed token containing claims (user_id, roles, expiry). The client includes the token in the `Authorization: Bearer` header. Servers verify the signature without a database lookup, enabling horizontal scaling. Key management: use RS256 (asymmetric) for services that need to verify but not issue tokens; use HS256 only when issuer and verifier are the same service.

JWT pitfalls: short expiry (15-60 minutes) limits the blast radius of token theft. Never store JWTs in localStorage (XSS-vulnerable); use httpOnly, Secure, SameSite=Strict cookies or memory. Implement a refresh token flow: short-lived access tokens + long-lived refresh tokens stored securely; refresh tokens rotate on use and can be revoked via a blacklist.

OAuth 2.0 with PKCE (Proof Key for Code Exchange) is the correct flow for public clients (SPAs, mobile apps). The code challenge prevents authorization code interception attacks. Never use the implicit flow—it exposes tokens in URLs and was deprecated in OAuth 2.1.

Role-Based Access Control (RBAC) assigns permissions to roles; users receive roles. Attribute-Based Access Control (ABAC) evaluates policies against subject, resource, action, and environment attributes—more expressive but more complex. For most applications, RBAC with fine-grained permissions is sufficient. Open Policy Agent (OPA) implements policy-as-code for both models.

## Zero-Trust Architecture

Zero-trust assumes no implicit trust based on network location—every request must be authenticated and authorized regardless of origin (inside or outside the perimeter). Core principles: verify explicitly (authenticate and authorize every request), use least privilege (minimal access rights, just-in-time provisioning), assume breach (design for contained lateral movement).

Service-to-service authentication uses mutual TLS (mTLS): both client and server present certificates. Service meshes (Istio) automate certificate rotation and mTLS enforcement. SPIFFE/SPIRE provides workload identity that integrates with Kubernetes service accounts, AWS IAM, and GCP service accounts.

Network segmentation limits blast radius: services communicate only with services they need to. Kubernetes NetworkPolicy restricts pod-to-pod traffic. AWS security groups and NACLs enforce at the VPC level. Firewall rules at the application layer add defense in depth.

## Secrets Management

Secrets (API keys, database passwords, certificates) must never appear in code, environment files committed to version control, or Docker images. Secrets managers (HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager) provide centralized storage with access logging, rotation, and fine-grained IAM.

Secret rotation: database passwords should rotate every 30-90 days. Vault's dynamic secrets generate ephemeral credentials on demand with short TTLs—eliminates stored credentials entirely. AWS Secrets Manager can rotate RDS credentials automatically by triggering a Lambda.

Kubernetes secrets are base64-encoded, not encrypted by default. Enable encryption at rest with KMS-backed EncryptionConfiguration. Sealed Secrets or External Secrets Operator synchronize secrets from Vault/AWS Secrets Manager into Kubernetes without storing plaintext in Git.

For development: `.env` files work but must be in `.gitignore`. `direnv` loads `.envrc` automatically on directory entry. `1Password` CLI and AWS SSM Parameter Store provide developer-friendly secret retrieval without storing secrets locally.

## OWASP Top 10 Defense Patterns

Injection (SQL, NoSQL, command): use parameterized queries/prepared statements exclusively. ORMs help but direct string concatenation with user input must be prohibited. Validate and sanitize input at API boundaries. Use allowlists (not blocklists) for expected values.

XSS (Cross-Site Scripting): React and modern frameworks escape output by default. `dangerouslySetInnerHTML` bypasses this—sanitize with DOMPurify. Set `Content-Security-Policy` header to restrict script sources. httpOnly cookies are immune to JavaScript theft. Subresource Integrity (SRI) hashes on third-party scripts prevent CDN compromise.

Insecure Direct Object References: use randomly generated UUIDs (not sequential integers) as resource IDs to prevent enumeration. Always verify that the authenticated user is authorized to access the requested resource—never rely on the ID being unguessable as the sole protection.

Security headers: `Strict-Transport-Security: max-age=31536000; includeSubDomains` enforces HTTPS. `X-Content-Type-Options: nosniff` prevents MIME sniffing. `X-Frame-Options: DENY` prevents clickjacking. `Permissions-Policy` restricts browser feature access. Implement with a middleware or CDN configuration, not per-endpoint.
