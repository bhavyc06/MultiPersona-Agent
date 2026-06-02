# API Design Patterns

## REST vs. GraphQL vs. gRPC

REST (Representational State Transfer) uses HTTP methods (GET, POST, PUT, PATCH, DELETE) on resource URLs. Its strengths are universal client support, HTTP caching, stateless semantics, and simplicity. Weaknesses: over-fetching (response includes unused fields), under-fetching (multiple round trips for related data), and no type safety across service boundaries without additional tooling (OpenAPI).

GraphQL provides a typed schema and query language that lets clients request exactly the fields they need. Eliminates over/under-fetching. Best suited for: public APIs with diverse client types (mobile, web, third-party), product APIs where frontend teams want autonomy, and schemas with many related entities. Weaknesses: HTTP caching is complex (all queries via POST), N+1 query problems require DataLoader patterns, and introspection can expose schema to attackers.

gRPC uses Protocol Buffers (binary serialization) over HTTP/2. Advantages: strongly typed contracts (.proto files), efficient binary encoding (3-10x smaller than JSON), bidirectional streaming, native code generation for 10+ languages. Required for inter-service communication in performance-sensitive microservices, mobile SDKs, and streaming APIs. Weakness: not human-readable, limited browser support (requires grpc-web proxy), debugging tools less mature than REST.

Choosing: public consumer APIs → REST; product BFFs with many client types → GraphQL; internal microservices with performance requirements → gRPC; streaming data → gRPC or WebSocket.

## API Versioning

URI versioning (`/api/v1/users`) is the most common and visible approach. Versions are explicit in the URL, easy to cache, easy to route via reverse proxy. Drawback: clients must upgrade explicitly; maintaining multiple versions simultaneously increases operational burden.

Header versioning (`Accept: application/vnd.myapi.v2+json`) keeps URLs stable. Cleaner semantically but harder to test (curl, browser less convenient), less visible in logs. 

Breaking changes that require a new version: removing fields, changing field types, changing semantics of existing fields, requiring new mandatory fields. Non-breaking changes can be made in the same version: adding optional fields, adding new endpoints, relaxing validation constraints.

Sunset policy: publish deprecation dates with a minimum 6-12 month notice. Use `Sunset` and `Deprecation` HTTP response headers to signal to clients. Log client calls to deprecated endpoints to identify who needs to migrate.

## Rate Limiting and Quotas

Token bucket algorithm: each client has a bucket that fills at a fixed rate (e.g., 100 tokens/minute). Each request consumes tokens. Bursting is allowed until the bucket empties. Suitable for most APIs.

Sliding window rate limiting: maintains a time-sorted log of requests and counts within the window. More accurate than fixed windows (which can allow 2x the limit at window boundaries) but more memory-intensive. Redis sorted sets implement sliding windows efficiently.

Rate limit response: return `429 Too Many Requests` with `Retry-After` header specifying when the client can retry. Include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers on all responses so clients can self-throttle.

Quota tiers: per-second rate limits prevent burst abuse; daily/monthly quotas enable billing tiers. Stripe, Twilio, and most public APIs layer both. API keys scoped to quota buckets in Redis allow per-customer limits without database queries on hot paths.

## API Gateway Patterns

API gateways (Kong, AWS API Gateway, Nginx, Envoy, Traefik) handle cross-cutting concerns: authentication, rate limiting, logging, CORS, TLS termination, request/response transformation, and routing. Moving these concerns out of application code reduces duplication and centralizes policy enforcement.

Service mesh (Istio, Linkerd) vs. API gateway: service meshes provide east-west traffic management (service-to-service inside the cluster) with mutual TLS, circuit breaking, and distributed tracing via sidecars. API gateways manage north-south traffic (external to internal). Most mature architectures use both.

Circuit breaker pattern: after N failures within a time window, the circuit opens and subsequent requests fail immediately without attempting the downstream call. This prevents cascade failures. After a timeout, the circuit enters half-open state and allows a probe request. If the probe succeeds, the circuit closes. Hystrix (deprecated), Resilience4j, and Polly implement circuit breakers.

Backend for Frontend (BFF): a dedicated API gateway per client type (mobile, web, public API). Each BFF aggregates calls from multiple microservices and returns the exact shape the client needs. Reduces client complexity and lets mobile and web teams evolve independently without coupling to a shared API contract.
