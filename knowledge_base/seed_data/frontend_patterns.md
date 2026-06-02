# Frontend Architecture Patterns

## React State Management

Local component state (`useState`, `useReducer`) handles UI-specific state that doesn't need sharing. Server state—remote data, cache, loading states—belongs in dedicated libraries: React Query (TanStack Query) or SWR handle fetching, caching, deduplication, and background refetching. These libraries eliminate 80% of manual `useEffect` data-fetching patterns.

Global application state (authentication, theme, user preferences) fits Zustand (lightweight, minimal boilerplate) or Jotai (atomic, bottom-up). Redux Toolkit remains appropriate for large teams with complex state machines, time-travel debugging requirements, or significant existing Redux investment. Avoid Redux for new projects unless team familiarity or state complexity genuinely warrants it.

Context API is not a state management solution—it's a dependency injection mechanism. Putting frequently-updated state in Context causes cascading re-renders across the tree. Use Context for stable, infrequently-changing values (theme, locale, auth user) and external stores for dynamic data.

React Query key patterns: string arrays for hierarchical cache keys (`['users', userId, 'posts']`); invalidation by key prefix enables targeted cache clearing; `staleTime` balances freshness with request count.

## Server-Side Rendering vs. Client-Side Rendering

Client-side rendering (CSR): browser downloads a minimal HTML shell, JavaScript bundle, and then renders. First Contentful Paint is delayed until JS executes. Suitable for authenticated dashboards where SEO is irrelevant and interactivity is the primary concern. Create React App and Vite produce CSR applications.

Server-side rendering (SSR): server renders HTML for the initial request. Faster First Contentful Paint, better SEO, better performance on low-end devices. Next.js is the dominant React SSR framework. `getServerSideProps` renders per-request; `getStaticProps` with ISR generates static HTML with periodic revalidation.

Static Site Generation (SSG) pre-builds all pages at deploy time. Fastest TTFB, CDN-cacheable, no server required. Suitable for content that changes infrequently (documentation, marketing). Astro and Next.js (with static export) support SSG with partial hydration (islands architecture).

Hydration mismatch errors occur when server-rendered HTML differs from client-rendered output. Common causes: `Date.now()`, `Math.random()`, browser-only APIs in component body. Move these to `useEffect` to run only client-side.

## Real-Time UI Patterns

Server-Sent Events (SSE) enable server-to-client push over standard HTTP. The client opens an `EventSource` connection; the server streams text events. SSE is unidirectional (server pushes only), automatically reconnects on disconnect, and works through HTTP/2 and standard proxies. Ideal for live dashboards, progress streams, and notification feeds.

WebSocket provides full-duplex communication. Required when the client also needs to push high-frequency data to the server (collaborative editing, multiplayer games, trading feeds). Higher operational complexity: WebSocket connections require sticky sessions or a pub/sub backend (Redis Pub/Sub, Socket.io adapter) when horizontally scaling.

Long polling: client sends a request and server holds it open until data is available (up to 30-60s), then responds. Client immediately sends another request. Simpler to implement than SSE/WebSocket, works with all HTTP infrastructure, but inefficient at scale (connections consume server threads/memory).

For the EventSource API: reconnection is automatic with `retry` field. Last-Event-ID header allows the server to replay missed events on reconnect. Use named events (`event: agent_start`) to route to specific handlers in the client. Don't forget to close the EventSource when the component unmounts to prevent memory leaks.

## Progressive Web App Patterns

PWA capabilities require a manifest.json (app icon, theme color, display mode) and a service worker. The service worker intercepts network requests, enabling offline support, background sync, and push notifications.

Cache-first strategy: serve from cache; update cache from network in background. Suitable for static assets (CSS, JS, images). Network-first: fetch from network; fall back to cache on failure. Suitable for API responses where freshness is important. Stale-while-revalidate: serve from cache immediately; revalidate in background.

Workbox (Google) simplifies service worker development with pre-built strategies and automatic cache invalidation. Vite PWA plugin integrates Workbox with Vite builds. The service worker lifecycle (install → activate → fetch) requires careful versioning: new service workers wait for old clients to close before activating.

Core Web Vitals: Largest Contentful Paint (LCP, target <2.5s) measures loading; First Input Delay / Interaction to Next Paint (INP, target <200ms) measures interactivity; Cumulative Layout Shift (CLS, target <0.1) measures visual stability. Improving LCP: preload critical resources, use CDN, optimize images. Improving INP: reduce JavaScript execution time, use `useDeferredValue` for expensive renders.
