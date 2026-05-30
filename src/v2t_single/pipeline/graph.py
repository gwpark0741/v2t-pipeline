from langgraph.graph import END, START, StateGraph

from v2t_single.pipeline.nodes.preprocessing import run_preprocessing
from v2t_single.pipeline.nodes.build_prompt import run_build_prompt
from v2t_single.pipeline.nodes.track_extraction import run_track_extraction
from v2t_single.pipeline.nodes.multi_agent import (
    run_draft_track_inventory,
    run_finalize_tracks,
    run_model_routing,
    run_timestamp_refinement,
    run_timestamp_task_planning,
)
from v2t_single.pipeline.state import PipelineState


def build_graph():
    """Phase 1 baseline용 LangGraph 파이프라인 생성"""
    graph = StateGraph(PipelineState)

    graph.add_node("preprocessing", run_preprocessing)
    graph.add_node("build_prompt", run_build_prompt)
    graph.add_node("track_extraction", run_track_extraction)

    graph.add_edge(START, "preprocessing")
    graph.add_edge("preprocessing", "build_prompt")
    graph.add_edge("build_prompt", "track_extraction")
    graph.add_edge("track_extraction", END)

    return graph.compile()


def build_multi_graph():
    """Multi-agent V2T 파이프라인 생성."""
    graph = StateGraph(PipelineState)

    graph.add_node("preprocessing", run_preprocessing)
    graph.add_node("draft_track_inventory", run_draft_track_inventory)
    graph.add_node("timestamp_task_planning", run_timestamp_task_planning)
    graph.add_node("timestamp_refinement", run_timestamp_refinement)
    graph.add_node("model_routing", run_model_routing)
    graph.add_node("finalize_tracks", run_finalize_tracks)

    graph.add_edge(START, "preprocessing")
    graph.add_edge("preprocessing", "draft_track_inventory")
    graph.add_edge("draft_track_inventory", "timestamp_task_planning")
    graph.add_edge("timestamp_task_planning", "timestamp_refinement")
    graph.add_edge("timestamp_refinement", "model_routing")
    graph.add_edge("model_routing", "finalize_tracks")
    graph.add_edge("finalize_tracks", END)

    return graph.compile()

graph = build_graph()
