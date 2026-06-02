# Project Delivery Patterns

## Agile Estimation Techniques

Story point estimation quantifies relative complexity, not absolute time. The Fibonacci-like sequence (1, 2, 3, 5, 8, 13, 21) forces teams to acknowledge uncertainty at larger sizes. Planning poker surfaces disagreement—when estimates diverge, the outlier reveals hidden complexity or misunderstanding. Teams should calibrate against a reference story: "what does a 3 feel like?"

Velocity-based forecasting: track completed story points per sprint over 6+ sprints to establish a reliable range. Use the lower quartile (not the average) for commitments to external stakeholders. Sprint velocity varies by team composition, holidays, and technical debt load—normalize for these factors.

T-shirt sizing (XS, S, M, L, XL) enables rapid estimation during discovery before stories are decomposed. Map sizes to time ranges post-estimation: XS = 1-2 days, S = 3-5 days, M = 1-2 weeks, L = 2-4 weeks, XL = requires decomposition.

Three-point estimation (PERT): (optimistic + 4×most-likely + pessimistic) ÷ 6. The pessimistic estimate forces teams to acknowledge tail risk. Aggregated across stories, PERT estimates produce more accurate release forecasts than single-point estimates by accounting for the asymmetric nature of software delays.

## Risk Management Frameworks

Risk register: document risks as "event → consequence" pairs. Score each on probability (1-5) and impact (1-5). Prioritize by expected value (probability × impact). For each high-priority risk: Mitigate (reduce probability or impact), Transfer (insurance, contract), Accept (acknowledge and monitor), or Avoid (change the plan).

Technical risk categories: integration risk (third-party APIs, legacy systems), performance risk (scale assumptions), technology risk (new tools, experimental frameworks), and knowledge risk (single points of expertise). Technical spikes—time-boxed proof-of-concept work—retire risk early before the team builds on uncertain foundations.

Dependency mapping: list all external dependencies (APIs, teams, infrastructure, regulatory approvals). For each critical path dependency, identify: who owns it, when it must be ready, what the team does if it's delayed, and whether there's a workaround. Dependencies are a leading indicator of project delays.

## Phased Delivery and MVP Scoping

Phased delivery reduces risk by delivering value early and validating assumptions with real users before full commitment. Phase 1 (MVP): the minimum feature set that delivers core value and validates the primary hypothesis. Phase 2: features that increase adoption or engagement. Phase 3: features for scale, compliance, and operational maturity.

The MoSCoW framework classifies scope: Must Have (launch blockers), Should Have (important but workaroundable), Could Have (nice to have), Won't Have (explicitly out of scope). Stakeholders commonly over-fill Must Have. Challenge by asking: "What happens if we ship without this?" Often Should Have reveals itself.

Feature flagging enables phased rollout and instant rollback without deployment. Progressive delivery—rolling out to 1%, 10%, 50%, 100% of users—lets teams validate stability at each stage. Feature flags decouple deploy (code change goes live) from release (feature becomes visible). This is a forcing function for good code hygiene: flagged code must handle both the enabled and disabled state.

Kill switches: identify the 3-5 features that, if they fail at scale, would require immediate reversal. Pre-build toggles for these features before launch. A kill switch should reduce traffic or disable a feature in under 5 minutes without a deployment.

## Team Topology and Sequencing

Conway's Law states that system design mirrors the communication structure of the team that builds it. Deliberately designing teams around desired architecture (Inverse Conway Maneuver) aligns incentives. Stream-aligned teams own end-to-end slices of the product. Platform teams build internal developer platforms. Enabling teams provide temporary expertise to stream-aligned teams.

Critical path sequencing: identify tasks where delay directly delays delivery. Float (slack) on non-critical tasks can absorb delays without impacting the deadline. Map dependencies to reveal the critical path early; actively manage it rather than tracking all tasks equally.

Onboarding time matters: a new engineer contributes negatively for 2-4 weeks (requires context, breaks things, pulls senior time). Adding engineers to a late project often makes it later (Brooks's Law). Mitigate with excellent documentation, runbooks, architecture decision records (ADRs), and sandbox environments that enable self-serve onboarding.
