"""
LLM Agent for Munich Open Data analysis
Uses LangGraph for workflow, DuckDB for SQL execution
Integrates with data layer for districts and cached datasets
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from .vector_store import VectorStore
from .tools import select_best_resource, analyze_csv, analyze_geospatial

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """LangGraph state for the data analysis agent"""
    messages: List[BaseMessage]
    selected_dataset: Optional[Dict[str, Any]]
    analysis_result: Optional[Dict[str, Any]]
    districts_context: Optional[str]


class ChatAgent:
    """
    LLM-powered agent for analyzing Munich Open Data.

    Features:
    - Semantic dataset search via ChromaDB
    - SQL generation for CSV and GeoJSON data
    - District awareness for spatial queries
    - Grounded responses (no hallucination)
    """

    def __init__(self, db=None, vector_store: VectorStore = None):
        self.db = db
        self.vector_store = vector_store or VectorStore()
        self._graph = None
        self._districts_cache = None

    @property
    def graph(self):
        """Lazy-load the compiled LangGraph"""
        if self._graph is None:
            self._graph = self._build_graph()
        return self._graph

    def get_districts_context(self) -> str:
        """Get district information for the LLM context"""
        if self._districts_cache:
            return self._districts_cache

        try:
            if self.db is None:
                from data.database import Database
                self.db = Database()

            from data.districts import DistrictService
            service = DistrictService(self.db)
            districts = service.get_districts('munich')

            if districts:
                lines = ["Munich has 25 administrative districts (Stadtbezirke):"]
                for d in sorted(districts, key=lambda x: x.number):
                    lines.append(f"- {d.number}: {d.name}")
                self._districts_cache = "\n".join(lines)
            else:
                self._districts_cache = ""
        except Exception as e:
            logger.warning(f"Could not load districts: {e}")
            self._districts_cache = ""

        return self._districts_cache

    def query(self, user_query: str) -> str:
        """
        Process a user query and return the answer.
        """
        state: AgentState = {
            "messages": [HumanMessage(content=user_query)],
            "selected_dataset": None,
            "analysis_result": None,
            "districts_context": self.get_districts_context(),
        }

        final_state = self.graph.invoke(state)

        # Extract final AI message
        messages = final_state["messages"]
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return msg.content

        return "I could not generate an answer."

    def _build_graph(self):
        """Construct the LangGraph workflow"""
        graph = StateGraph(AgentState)

        graph.add_node("lookup_dataset", self._node_lookup_dataset)
        graph.add_node("execute_tool", self._node_execute_tool)
        graph.add_node("generate_answer", self._node_generate_answer)

        graph.set_entry_point("lookup_dataset")
        graph.add_edge("lookup_dataset", "execute_tool")
        graph.add_edge("execute_tool", "generate_answer")
        graph.add_edge("generate_answer", END)

        return graph.compile()

    def _get_last_user_message(self, state: AgentState) -> str:
        """Extract the last user message from state"""
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                return msg.content if isinstance(msg.content, str) else str(msg.content)
        return ""

    def _node_lookup_dataset(self, state: AgentState) -> AgentState:
        """Find the best dataset for the query"""
        user_query = self._get_last_user_message(state)

        # Search vector store
        hits = self.vector_store.search(user_query, n_results=3)

        if not hits:
            return {**state, "selected_dataset": None}

        primary = hits[0]

        # Parse resources
        raw_resources = primary.get("resources") or "[]"
        if isinstance(raw_resources, str):
            try:
                resources = json.loads(raw_resources)
            except json.JSONDecodeError:
                resources = []
        else:
            resources = raw_resources or []

        # Select best resource
        best_resource = select_best_resource(resources)

        match = {
            "id": primary.get("id"),
            "title": primary.get("title"),
            "description": primary.get("description"),
            "resources": resources,
            "selected_resource": best_resource,
        }

        return {**state, "selected_dataset": match}

    def _node_execute_tool(self, state: AgentState) -> AgentState:
        """Execute analysis on the selected dataset"""
        dataset = state.get("selected_dataset")
        if not dataset:
            return {**state, "analysis_result": None}

        selected_resource = dataset.get("selected_resource") or {}
        fmt = (selected_resource.get("format") or "").upper()
        url = selected_resource.get("url")
        user_query = self._get_last_user_message(state)

        if not url:
            analysis_result = {
                "error": "no_resource_url",
                "error_message": "Dataset found, but no usable file URL.",
            }
        elif fmt == "CSV":
            analysis_result = analyze_csv(url, user_query)
        elif fmt in {"GEOJSON", "WFS", "JSON"}:
            analysis_result = analyze_geospatial(url, user_query)
        else:
            analysis_result = {
                "error": "unsupported_format",
                "error_message": f"Format '{fmt}' is not yet supported.",
            }

        return {**state, "analysis_result": analysis_result}

    def _node_generate_answer(self, state: AgentState) -> AgentState:
        """Generate final answer using LLM"""
        user_query = self._get_last_user_message(state)
        dataset = state.get("selected_dataset")
        analysis = state.get("analysis_result")
        districts_context = state.get("districts_context", "")

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)

        # Build system prompt
        system_prompt = (
            "You are a data analyst for the City of Munich Open Data Portal.\n"
            "You MUST NOT hallucinate data. Only use what's shown in the preview.\n"
            "If the data doesn't answer the question, say so explicitly.\n\n"
            "You receive:\n"
            "- The user question\n"
            "- Dataset metadata\n"
            "- Data preview as markdown table\n\n"
            "Instructions:\n"
            "- Use ONLY the data in the preview for facts and values.\n"
            "- You MAY use general Munich geographic knowledge for context.\n"
            "- Present tabular results as markdown tables when suitable.\n"
        )

        if districts_context:
            system_prompt += f"\nMunich district reference:\n{districts_context}\n"

        # Build dataset text
        dataset_text = "No dataset found."
        if dataset:
            dataset_text = f"Dataset: {dataset.get('title')}\n"
            dataset_text += f"Description: {dataset.get('description', '')[:500]}\n"
            res = dataset.get("selected_resource") or {}
            if res:
                dataset_text += f"Resource: {res.get('name')} ({res.get('format')})\n"

        # Build analysis text
        analysis_text = "No analysis available."
        if analysis:
            if analysis.get("error"):
                analysis_text = f"Error: {analysis.get('error_message')}"
            else:
                analysis_text = f"SQL: {analysis.get('sql_query', 'N/A')}\n\n"
                analysis_text += f"Results ({analysis.get('row_count', 0)} rows):\n"
                analysis_text += analysis.get('preview_markdown', '')

        messages = [
            AIMessage(content=system_prompt),
            HumanMessage(content=(
                f"User question:\n{user_query}\n\n"
                f"Dataset:\n{dataset_text}\n\n"
                f"Analysis:\n{analysis_text}\n\n"
                "Answer the question using ONLY this information."
            )),
        ]

        response = llm.invoke(messages)

        new_messages = list(state["messages"])
        new_messages.append(AIMessage(content=response.content))

        return {**state, "messages": new_messages}


# Convenience function
def build_graph():
    """Build and return a compiled LangGraph (for legacy compatibility)"""
    agent = ChatAgent()
    return agent.graph
