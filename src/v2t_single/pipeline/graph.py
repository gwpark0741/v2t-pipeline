from langgraph.graph import END, START, StateGraph

from v2t_single.pipeline.nodes.preprocessing import run_preprocessing
from v2t_single.pipeline.nodes.build_prompt import run_build_prompt
from v2t_single.pipeline.nodes.track_extraction import run_track_extraction
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

graph = build_graph()