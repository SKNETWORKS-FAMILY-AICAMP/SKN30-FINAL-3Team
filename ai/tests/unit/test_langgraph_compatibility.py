from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    count: int


def increment(state: State) -> State:
    return {"count": state["count"] + 1}


def test_minimal_graph_compiles_on_supported_python() -> None:
    builder = StateGraph(State)
    builder.add_node("increment", increment)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)

    graph = builder.compile()

    assert graph.invoke({"count": 1}) == {"count": 2}
