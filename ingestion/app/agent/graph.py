from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    answer_node,
    formatter_node,
    plan_node,
    prepare_action_node,
    retrieve_node,
    route_intent_node,
)
from app.agent.state import AgentState


def _after_retrieve(state: AgentState) -> str:
    if state.intent in {
        "gmail_draft",
        "gmail_send",
        "docs_create",
        "docs_update",
        "sheets_create",
        "sheets_update",
    }:
        return "prepare_action"
    return "answer"


def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("route_intent", route_intent_node)
    graph.add_node("plan", plan_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("prepare_action", prepare_action_node)
    graph.add_node("answer", answer_node)
    graph.add_node("format", formatter_node)

    graph.add_edge(START, "route_intent")
    graph.add_edge("route_intent", "plan")
    graph.add_edge("plan", "retrieve")
    graph.add_conditional_edges(
        "retrieve",
        _after_retrieve,
        {
            "answer": "answer",
            "prepare_action": "prepare_action",
        },
    )
    graph.add_edge("prepare_action", "answer")
    graph.add_edge("answer", "format")
    graph.add_edge("format", END)

    return graph.compile()


agent_graph = build_agent_graph()
