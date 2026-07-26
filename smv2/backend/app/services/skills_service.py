"""Pure derivation functions for skill graph levels, mastery, and status."""

# Constants
QUIZ_WEIGHT = 0.5
PRACTICE_WEIGHT = 0.3
SRS_WEIGHT = 0.2
STRUGGLING_BELOW = 40
SOLID_ABOVE = 70
WEAK_PREREQ_BELOW = 60


def derive_levels(node_ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """
    Compute longest-path depth for each node in a DAG.

    Uses Kahn's algorithm to detect cycles and track the longest path from any root.
    Levels are 1-based (roots start at 1).

    Args:
        node_ids: List of node identifiers
        edges: List of (from, to) tuples representing directed edges

    Returns:
        Dictionary mapping node_id to its level (1-based)

    Raises:
        ValueError: If the graph contains a cycle or an edge references an unknown node
    """
    # Build adjacency list and track in-degrees
    graph = {node: [] for node in node_ids}
    in_degree = {node: 0 for node in node_ids}

    # Validate that all edge endpoints are in node_ids
    for from_node, to_node in edges:
        if from_node not in graph:
            raise ValueError(f"edge references unknown node: {from_node}")
        if to_node not in graph:
            raise ValueError(f"edge references unknown node: {to_node}")
        graph[from_node].append(to_node)
        in_degree[to_node] += 1

    # Initialize levels (will update with longest paths)
    levels = {node: 0 for node in node_ids}

    # Kahn's algorithm: start with nodes that have no incoming edges (roots)
    queue = [node for node in node_ids if in_degree[node] == 0]
    processed_count = 0

    while queue:
        current = queue.pop(0)
        processed_count += 1

        # Set level for current node if not yet set or if this is a longer path
        if levels[current] == 0:
            levels[current] = 1

        # Update all children
        for child in graph[current]:
            # Track longest path to this child
            levels[child] = max(levels[child], levels[current] + 1)

            # Decrease in-degree
            in_degree[child] -= 1

            # If in-degree becomes 0, child is ready to process
            if in_degree[child] == 0:
                queue.append(child)

    # Check for cycle: if not all nodes were processed, there's a cycle
    if processed_count != len(graph):
        raise ValueError("cycle")

    return levels


def mastery_score(
    practice: float | None, srs: float | None, quiz: float | None
) -> int:
    """
    Calculate mastery score from weighted signals.

    Each signal is in [0, 1] or None. Weights are renormalized over present signals.
    Result is scaled to 0-100 and rounded.

    Args:
        practice: Practice signal (0-1) or None
        srs: SRS signal (0-1) or None
        quiz: Quiz signal (0-1) or None

    Returns:
        Mastery score (0-100), rounded
    """
    if practice is None and srs is None and quiz is None:
        return 0

    # Collect present signals and their weights
    signals = []
    weights = []

    if practice is not None:
        signals.append(practice)
        weights.append(PRACTICE_WEIGHT)

    if srs is not None:
        signals.append(srs)
        weights.append(SRS_WEIGHT)

    if quiz is not None:
        signals.append(quiz)
        weights.append(QUIZ_WEIGHT)

    # Compute weighted sum using original weights
    numerator = sum(s * w for s, w in zip(signals, weights))
    total_weight = sum(weights)

    # Scale to 0-100 and round (multiply by 100 before dividing to minimize precision loss)
    return round((numerator * 100) / total_weight)


def status_for(mastery: int, has_any_signal: bool, weak_prereq: bool) -> str:
    """
    Determine mastery status based on score and prerequisites.

    Status priority:
    1. "locked" if no signal AND weak prerequisite
    2. "growing" if no signal AND no weak prerequisite (new, unblocked learner)
    3. "struggling" if mastery < STRUGGLING_BELOW
    4. "solid" if mastery > SOLID_ABOVE
    5. "growing" otherwise

    Args:
        mastery: Mastery score (0-100)
        has_any_signal: Whether the learner has any recorded signals
        weak_prereq: Whether a prerequisite is below WEAK_PREREQ_BELOW threshold

    Returns:
        Status string: "locked", "struggling", "growing", or "solid"
    """
    # Check locked gate first: no signal AND weak prerequisite blocks access
    if not has_any_signal and weak_prereq:
        return "locked"

    # New learners with no signals are "growing" (unblocked, just starting)
    if not has_any_signal:
        return "growing"

    # Threshold-based status for learners with signals
    if mastery < STRUGGLING_BELOW:
        return "struggling"

    if mastery > SOLID_ABOVE:
        return "solid"

    # Default to growing for those making progress
    return "growing"
