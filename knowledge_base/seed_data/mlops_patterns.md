# MLOps Patterns

## Model Serving Architecture

Model serving divides into three patterns based on latency requirements. Online serving handles synchronous prediction requests with p99 latency targets under 100ms. Batch serving processes large datasets offline, typically triggered on a schedule or event. Near-real-time serving uses micro-batching (1-5 second windows) to amortize request overhead while staying responsive.

For online serving, the serving stack commonly consists of: a model server (TorchServe, TF Serving, Triton Inference Server, or vLLM for LLMs), a feature retrieval layer, and an API gateway for authentication and rate limiting. Triton supports multiple model frameworks and hardware backends (CPU, GPU, multiple GPUs) in a single server, reducing operational footprint.

Canary deployments split traffic between model versions using weighted routing. A/B tests and shadow deployments are distinct patterns: A/B assigns users deterministically (by user_id hash) for statistical validity; shadow mode runs the new model on all production traffic but discards predictions, enabling validation without business risk. Gradual rollout (1% → 10% → 50% → 100%) combines both by starting with shadow then promoting to canary.

## Feature Stores

Feature stores solve the training-serving skew problem by providing a unified interface for feature computation. The dual-storage pattern separates concerns: the offline store (data lake, Iceberg, Delta Lake) serves training with historical point-in-time correct feature values; the online store (Redis, DynamoDB, Cassandra) serves inference with sub-10ms latency.

Point-in-time correct joins prevent label leakage in training. When assembling training data, features must be retrieved as they existed at the event timestamp, not as they exist today. Without this, a model trained on "account age" might use today's value when labeling historical fraud events—the model will appear to perform well but fail in production.

Feature freshness requirements drive the compute architecture. Features derived from real-time event streams (last 5 minutes of user activity) require streaming pipelines (Flink, Kafka Streams). Features derived from daily aggregates can use batch jobs (Spark, dbt). Many features fall in between and use lambda architecture: batch for historical backfill, streaming for incremental updates.

## Drift Detection

Model performance degrades due to three types of drift. Data drift (covariate shift): input feature distributions change—for example, a demographic shift in the user base changes the age distribution. Concept drift (posterior shift): the relationship between features and the target changes—for example, a feature that predicted fraud changes meaning as fraud patterns evolve. Label drift: the distribution of outcomes changes.

Statistical tests for drift detection: Population Stability Index (PSI) is industry-standard for comparing feature distributions between reference and production windows. PSI < 0.1 indicates no significant drift; 0.1-0.2 indicates moderate drift requiring investigation; > 0.2 indicates significant drift. Kolmogorov-Smirnov tests provide a non-parametric alternative. For model output drift, track the distribution of prediction scores and compare against a reference window.

Automated retraining pipelines trigger when drift exceeds thresholds or on a schedule (weekly, monthly). Trigger-based retraining uses a challenger-champion pattern: the challenger is trained on recent data, validated on a holdout set, and promoted only if it outperforms the champion on business metrics. This prevents regression from noisy drift signals.

## CI/CD for Machine Learning

ML pipelines extend traditional CI/CD with data and model validation stages. A production ML pipeline typically includes: data validation (schema checks, distribution tests), feature engineering, model training, model evaluation (offline metrics against holdout set), model registry push, and optional shadow/canary deployment.

DVC (Data Version Control) tracks dataset and model artifacts alongside code in Git. MLflow tracks experiments, parameters, metrics, and model artifacts. Weights & Biases provides richer visualization and team collaboration. The choice depends on scale: DVC fits small teams storing artifacts in S3/GCS; MLflow fits teams needing experiment comparison; W&B fits larger teams with complex experiment tracking needs.

Infrastructure-as-code for ML: Kubeflow Pipelines and Metaflow define DAG-based ML workflows as code. Vertex AI Pipelines (GCP) and SageMaker Pipelines (AWS) provide managed orchestration with integrated feature stores, model registry, and deployment. Airflow remains common for teams already invested in it, though it lacks ML-specific concepts like experiment tracking and model versioning.
