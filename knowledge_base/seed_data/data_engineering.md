# Data Engineering Patterns

## Batch vs. Streaming Processing

Batch processing handles bounded datasets on a schedule. Spark, dbt, and SQL-based tools (BigQuery, Redshift) process large historical datasets efficiently using distributed query engines. Batch is simpler to reason about, easier to test, and more cost-effective for non-time-sensitive transformations. Typical latency: minutes to hours.

Streaming processing handles unbounded event streams with low latency requirements (seconds to milliseconds). Apache Kafka is the dominant messaging backbone; Apache Flink and Kafka Streams are the primary processing engines. Streaming adds operational complexity: state management, exactly-once semantics, late data handling, and watermarking require explicit design decisions that batch processing handles implicitly.

Lambda architecture combines batch and streaming: the batch layer recomputes accurate historical views on a schedule; the speed layer provides low-latency approximate views; a serving layer merges both. The appeal is resilience—the batch layer can correct streaming errors. The drawback is dual maintenance: two codebases computing the same logic.

Kappa architecture simplifies by processing everything as streams, using replayable Kafka topics as the source of truth. Historical reprocessing replays the full topic. This eliminates dual codebases but requires Kafka to retain data for replay (potentially terabytes) and requires streaming code that handles both historical and real-time data.

## Apache Kafka Architecture

Kafka is a distributed, partitioned, replicated commit log. Topics are divided into partitions; partitions are the unit of parallelism and ordering guarantee. Within a partition, ordering is strict. Across partitions, ordering is not guaranteed—applications needing global ordering must use a single partition (sacrificing parallelism) or implement sequence numbers.

Consumer groups enable parallel consumption. Each partition is consumed by exactly one consumer in a group; multiple groups can consume the same topic independently. To scale consumption, increase partitions—but partition count can only increase, never decrease, making initial over-provisioning a common strategy.

Replication factor of 3 is standard for production—one leader, two followers. The in-sync replica (ISR) set tracks which replicas are fully caught up. `acks=all` writes require acknowledgment from all ISRs before confirming, providing the strongest durability guarantee at the cost of write latency.

Exactly-once semantics (EOS) require idempotent producers (preventing duplicate messages on retry) and transactional producers (atomic multi-partition writes). Kafka Streams and Flink achieve end-to-end EOS by coordinating consumer offsets with sink writes in the same transaction.

## dbt and the Modern Data Stack

dbt (data build tool) transforms data in the warehouse using SQL SELECT statements. Models are defined as `.sql` files; dbt handles materializations (view, table, incremental), dependency resolution (DAG), testing (schema and custom data tests), and documentation generation.

The modern data stack separates ingestion (Fivetran, Airbyte), storage (Snowflake, BigQuery, Databricks), and transformation (dbt). This separation of concerns lets each layer scale and evolve independently. dbt Core is open source; dbt Cloud adds scheduling, CI, documentation hosting, and IDE features.

Incremental models process only new or changed data, reducing cost for large tables. The incremental strategy depends on the warehouse: `append` for event logs (no updates); `delete+insert` for slowly changing dimensions; `merge` for tables with updates. The `unique_key` configuration drives the merge logic.

## Data Lakehouse Architecture

The lakehouse combines data lake economics (cheap object storage) with data warehouse capabilities (ACID transactions, schema enforcement, query performance). Apache Iceberg, Delta Lake, and Apache Hudi provide the table format layer that adds transaction semantics and time travel to object storage.

Iceberg's key features: partition evolution (change partitioning without rewriting data), schema evolution (add/drop/rename columns), time travel (query any snapshot), and hidden partitioning (partition transforms transparent to users). Iceberg is the emerging standard, supported natively by Spark, Flink, Trino, Snowflake, and BigQuery.

Change Data Capture (CDC) moves operational database changes to analytics systems in near-real-time. Debezium captures PostgreSQL WAL, MySQL binlog, or SQL Server CDC records and publishes to Kafka. The downstream consumer writes Kafka records to the lakehouse, maintaining a consistent replica of the operational database for analytics without impacting production query performance.
