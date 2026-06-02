async def estimate_timeline(scope_json: dict) -> dict:
    """
    Rule-based delivery timeline estimate. No model call — pure heuristics.

    scope_json keys (all optional):
      complexity    : "simple" | "standard" | "complex"   (default: "standard")
      team_size     : int    — number of engineers          (default: 3)
      features_count: int    — number of distinct features  (default: 1)
    """
    complexity = scope_json.get("complexity", "standard")
    team_size = max(1, int(scope_json.get("team_size", 3)))
    features_count = max(1, int(scope_json.get("features_count", 1)))

    # Base phase durations (weeks) keyed by complexity
    base_phases: dict[str, dict[str, int]] = {
        "simple": {
            "Discovery & Design": 1,
            "Build": 3,
            "Test & Deploy": 1,
        },
        "standard": {
            "Discovery & Design": 2,
            "Architecture": 1,
            "Build": 6,
            "Test & Deploy": 2,
            "Stabilisation": 1,
        },
        "complex": {
            "Discovery & Design": 3,
            "Architecture": 2,
            "Data Layer": 4,
            "AI/ML Layer": 5,
            "Integration": 3,
            "Test & Deploy": 3,
            "Stabilisation": 2,
        },
    }

    base = base_phases.get(complexity, base_phases["standard"])

    # Scale by features and team size relative to reference (3 engineers, 1 feature)
    feature_scale = max(0.5, features_count / 3)
    team_scale = max(0.5, 3 / team_size)  # more engineers → faster (diminishing returns built-in)
    scale = feature_scale * team_scale

    phases = [{"name": name, "weeks": max(1, round(weeks * scale))} for name, weeks in base.items()]
    total_weeks = sum(p["weeks"] for p in phases)

    confidence_map = {"simple": "high", "standard": "medium", "complex": "low"}
    confidence = confidence_map.get(complexity, "medium")

    assumptions = [
        f"Team of {team_size} engineer(s) at full allocation",
        "Requirements stable after Discovery phase",
        "No major blocking external dependencies",
    ]
    if complexity == "complex":
        assumptions.append("Senior ML/data specialists available for AI/ML and Data Layer phases")
    if team_size < 2:
        assumptions.append("Single-engineer team — parallel tracks are sequential; estimates increase")

    return {
        "phases": phases,
        "total_weeks": total_weeks,
        "confidence": confidence,
        "assumptions": assumptions,
    }
