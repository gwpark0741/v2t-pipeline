from langgraph.graph import END, START, StateGraph

from pipeline.nodes.preprocessing import run_preprocessing
from pipeline.nodes.track_extraction import run_track_extraction
from pipeline.state import PipelineState


def build_graph():
    """Phase 1 baseline용 LangGraph 파이프라인 생성"""
    graph = StateGraph(PipelineState)

    graph.add_node("preprocessing", run_preprocessing)
    graph.add_node("track_extraction", run_track_extraction)

    graph.add_edge(START, "preprocessing")
    graph.add_edge("preprocessing", "track_extraction")
    graph.add_edge("track_extraction", END)

    return graph.compile()
