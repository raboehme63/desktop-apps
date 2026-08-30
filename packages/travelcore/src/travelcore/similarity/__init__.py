"""Reusable photo similarity component (phase 10). Independent of the GUI."""

from travelcore.similarity.clusters import (
    ClusterMarks,
    ClusterOverlay,
    ClusterRecord,
    accept_exact_stacks,
    create_manual_group,
    dismiss_cluster,
    load_cluster,
    load_cluster_overlay,
    propose_scene_groups,
    set_group_keys,
    set_stack_key,
)
from travelcore.similarity.types import (
    ClusterStatus,
    ClusterType,
    SimilarityGroup,
    SimilarityKind,
    SimilarityMethod,
)

__all__ = [
    "ClusterMarks",
    "ClusterOverlay",
    "ClusterRecord",
    "ClusterStatus",
    "ClusterType",
    "SimilarityGroup",
    "SimilarityKind",
    "SimilarityMethod",
    "accept_exact_stacks",
    "create_manual_group",
    "dismiss_cluster",
    "load_cluster",
    "load_cluster_overlay",
    "propose_scene_groups",
    "set_group_keys",
    "set_stack_key",
]
