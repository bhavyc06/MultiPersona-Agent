# Cloud Architecture Patterns

## Multi-Region and High Availability Design

Multi-region architectures distribute workloads across geographic regions to achieve low latency, disaster recovery, and regulatory compliance. The primary patterns are active-active (all regions serve live traffic), active-passive (standby region promotes on failure), and active-local (traffic routed to nearest region with global fallback).

For active-active deployments, data replication becomes the critical challenge. Conflict-free replicated data types (CRDTs) or last-write-wins strategies handle eventual consistency. DynamoDB Global Tables, Spanner, and CockroachDB are managed services designed for this pattern. Self-hosted alternatives require careful orchestration of raft-based consensus across regions.

Recovery time objectives (RTO) and recovery point objectives (RPO) drive architecture decisions. Sub-minute RTO demands warm standby with pre-loaded compute. Sub-second RPO demands synchronous replication, which introduces cross-region write latency of 50-200ms depending on geography. Many systems accept eventual consistency for reads but require strong consistency for financial or inventory transactions.

## VPC Design and Network Segmentation

Virtual Private Cloud (VPC) design establishes the network boundary for cloud workloads. Best practices follow the principle of least privilege: public subnets expose only load balancers and NAT gateways; private subnets host application servers; isolated subnets hold databases and internal services with no inbound internet routing.

Transit Gateway (AWS) or Cloud Router (GCP) enables hub-and-spoke connectivity between VPCs without full mesh peering. This reduces the O(n²) peering complexity to O(n) as environments grow. Shared VPC (GCP) or RAM-shared subnets (AWS) let multiple accounts use common network infrastructure without duplicating routing tables.

Security groups and network ACLs operate at different layers. Security groups are stateful (connection tracking), applied per-ENI, and evaluated before network ACLs. NACLs are stateless and evaluated on both ingress and egress. Production patterns layer both: NACLs block broad IP ranges, security groups enforce service-to-service allowlists.

## Managed vs. Self-Hosted Tradeoffs

Managed services (RDS, ElastiCache, MSK, CloudSQL) offload operational burden—patching, failover, backups, metrics—but reduce customization and can lock in to vendor pricing. Total cost of ownership calculations must include: engineering time for self-managed operations (typically 0.5-1 FTE per major data system), vendor support tiers, and data transfer costs.

Self-hosted Kubernetes (EKS, GKE, AKS) versus managed Kubernetes: managed control planes eliminate etcd management, cert rotation, and API server scaling but add $150-300/month/cluster and reduce version flexibility. For teams under 20 engineers, managed Kubernetes consistently delivers better reliability per engineering-hour.

Key decision signals favoring managed: compliance requirements (SOC2, HIPAA) where audit trails are pre-built; team lacking deep systems expertise; time-to-market pressure; workloads with variable scale. Signals favoring self-hosted: extreme cost sensitivity at scale; highly custom networking requirements; airgap/sovereign deployments; vendor pricing negotiations.

## Cost Optimization Patterns

Compute cost optimization follows a tier hierarchy: Reserved/Committed Use (1-3 year) for baseline predictable load (40-60% savings), Spot/Preemptible for fault-tolerant batch and stateless services (70-90% savings), On-Demand for variable and stateful workloads.

Right-sizing requires observability: P95 CPU and memory utilization over 14-day windows identify over-provisioned instances. AWS Compute Optimizer and GCP Recommender automate this analysis. Common finding: 30-40% of production instances run below 20% CPU utilization.

Storage tiering: hot data in SSD-backed block storage or in-memory; warm data in S3/GCS Standard or SSD with lifecycle policies; cold data in Glacier/Nearline/Archive. Data lifecycle policies that transition objects after 30 days to cheaper tiers reduce storage costs by 60-80% for analytics workloads with declining access patterns.
