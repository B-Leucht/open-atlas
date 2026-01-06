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
from .tools import (
    select_best_resource,
    analyze_csv,
    analyze_geospatial,
    classify_query,
    analyze_multiple_datasets,
    design_index,
    calculate_index_from_spec,
)

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """LangGraph state for the data analysis agent"""
    messages: List[BaseMessage]

    # Query classification
    query_type: Optional[str]  # "single_dataset", "multi_dataset", "index_creation"

    # Existing (backward compatible)
    selected_dataset: Optional[Dict[str, Any]]
    analysis_result: Optional[Dict[str, Any]]
    districts_context: Optional[str]

    # Multi-dataset support
    selected_datasets: List[Dict[str, Any]]
    analysis_results: List[Dict[str, Any]]
    combined_analysis: Optional[str]

    # Index creation
    suggested_index: Optional[Dict[str, Any]]
    index_result: Optional[Dict[str, Any]]


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

    def query(self, user_query: str) -> Dict[str, Any]:
        """
        Process a user query and return structured response.

        Returns:
            {
                "answer": str,
                "query_type": str,
                "index_result": Optional[Dict] - for index_creation queries
                "suggested_index": Optional[Dict] - index spec for index_creation
                "geo_data": Optional[Dict] - for queries with geographic results
            }
        """
        state: AgentState = {
            "messages": [HumanMessage(content=user_query)],
            "query_type": None,
            "selected_dataset": None,
            "analysis_result": None,
            "districts_context": self.get_districts_context(),
            "selected_datasets": [],
            "analysis_results": [],
            "combined_analysis": None,
            "suggested_index": None,
            "index_result": None,
        }

        final_state = self.graph.invoke(state)

        # Extract final AI message
        answer = "I could not generate an answer."
        messages = final_state["messages"]
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                answer = msg.content
                break

        # Build structured response
        response = {
            "answer": answer,
            "query_type": final_state.get("query_type", "single_dataset"),
        }

        # Include index data if this was an index creation query
        if final_state.get("query_type") == "index_creation":
            index_result = final_state.get("index_result")
            if index_result and index_result.get("success"):
                response["index_result"] = index_result
                response["suggested_index"] = final_state.get("suggested_index")

        # Include geographic data from analysis results if available
        analysis_result = final_state.get("analysis_result")
        if analysis_result and analysis_result.get("coordinates"):
            response["geo_data"] = {
                "type": "points",
                "coordinates": analysis_result["coordinates"],
                "dataset_title": final_state.get("selected_dataset", {}).get("title")
            }

        return response

    def query_text(self, user_query: str) -> str:
        """
        Process a user query and return just the answer text.
        For backward compatibility.
        """
        result = self.query(user_query)
        return result.get("answer", "I could not generate an answer.")

    def _build_graph(self):
        """Construct the LangGraph workflow with conditional routing"""
        graph = StateGraph(AgentState)

        # Add all nodes
        graph.add_node("classify_query", self._node_classify_query)

        # Single-dataset path (backward compatible)
        graph.add_node("single_lookup", self._node_lookup_dataset)
        graph.add_node("execute_tool", self._node_execute_tool)

        # Multi-dataset path
        graph.add_node("multi_lookup", self._node_lookup_datasets)
        graph.add_node("analyze_multi", self._node_analyze_multi)

        # Index creation path
        graph.add_node("design_index", self._node_design_index)
        graph.add_node("calculate_index", self._node_calculate_index)

        # Shared answer generation
        graph.add_node("generate_answer", self._node_generate_answer)

        # Entry point: classify the query first
        graph.set_entry_point("classify_query")

        # Conditional routing based on query type
        graph.add_conditional_edges(
            "classify_query",
            self._route_by_query_type,
            {
                "single_lookup": "single_lookup",
                "multi_lookup": "multi_lookup",
                "design_index": "design_index",
            }
        )

        # Single-dataset path edges
        graph.add_edge("single_lookup", "execute_tool")
        graph.add_edge("execute_tool", "generate_answer")

        # Multi-dataset path edges
        graph.add_edge("multi_lookup", "analyze_multi")
        graph.add_edge("analyze_multi", "generate_answer")

        # Index creation path edges
        graph.add_edge("design_index", "calculate_index")
        graph.add_edge("calculate_index", "generate_answer")

        # Terminal edge
        graph.add_edge("generate_answer", END)

        return graph.compile()

    def _get_last_user_message(self, state: AgentState) -> str:
        """Extract the last user message from state"""
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                return msg.content if isinstance(msg.content, str) else str(msg.content)
        return ""

    def _prepare_dataset(self, hit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Prepare a dataset hit with parsed resources and selected resource"""
        if not hit:
            return None

        raw_resources = hit.get("resources") or "[]"
        if isinstance(raw_resources, str):
            try:
                resources = json.loads(raw_resources)
            except json.JSONDecodeError:
                resources = []
        else:
            resources = raw_resources or []

        return {
            "id": hit.get("id"),
            "title": hit.get("title"),
            "description": hit.get("description"),
            "resources": resources,
            "selected_resource": select_best_resource(resources),
        }

    # =========================================================================
    # CLASSIFICATION NODE
    # =========================================================================

    def _node_classify_query(self, state: AgentState) -> AgentState:
        """Classify the query to determine processing path"""
        user_query = self._get_last_user_message(state)
        classification = classify_query(user_query)
        logger.info(f"Query classified as: {classification}")
        return {**state, "query_type": classification.get("query_type", "single_dataset")}

    def _route_by_query_type(self, state: AgentState) -> str:
        """Route to appropriate processing path based on query type"""
        query_type = state.get("query_type", "single_dataset")
        route_map = {
            "single_dataset": "single_lookup",
            "multi_dataset": "multi_lookup",
            "index_creation": "design_index",
        }
        return route_map.get(query_type, "single_lookup")

    # =========================================================================
    # SINGLE DATASET PATH (backward compatible)
    # =========================================================================

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

    # =========================================================================
    # MULTI-DATASET PATH
    # =========================================================================

    def _node_lookup_datasets(self, state: AgentState) -> AgentState:
        """Find multiple relevant datasets for comparative queries"""
        user_query = self._get_last_user_message(state)

        # Search for more datasets for multi-dataset analysis
        hits = self.vector_store.search(user_query, n_results=5)

        if not hits:
            return {**state, "selected_datasets": []}

        # Prepare all datasets
        datasets = []
        for hit in hits:
            prepared = self._prepare_dataset(hit)
            if prepared:
                datasets.append(prepared)

        logger.info(f"Multi-dataset lookup found {len(datasets)} datasets")
        return {**state, "selected_datasets": datasets}

    def _node_analyze_multi(self, state: AgentState) -> AgentState:
        """Analyze multiple datasets and combine results"""
        datasets = state.get("selected_datasets", [])
        user_query = self._get_last_user_message(state)

        if not datasets:
            return {
                **state,
                "analysis_results": [],
                "combined_analysis": "No datasets found for analysis."
            }

        result = analyze_multiple_datasets(datasets, user_query)

        return {
            **state,
            "analysis_results": result.get("individual_results", []),
            "combined_analysis": result.get("combined_analysis", ""),
        }

    # =========================================================================
    # INDEX CREATION PATH
    # =========================================================================

    def _node_design_index(self, state: AgentState) -> AgentState:
        """Design a composite index based on user query"""
        user_query = self._get_last_user_message(state)

        # Get available datasets for index creation
        if self.db is None:
            from data.database import Database
            self.db = Database()

        from data.indices import IndexCalculator
        calculator = IndexCalculator(self.db)
        available_datasets = calculator.get_available_datasets()

        # Use AI to design the index
        index_spec = design_index(user_query, available_datasets)

        logger.info(f"Designed index: {index_spec.get('name')} with {len(index_spec.get('components', []))} components")
        return {**state, "suggested_index": index_spec}

    def _node_calculate_index(self, state: AgentState) -> AgentState:
        """Calculate the designed index"""
        index_spec = state.get("suggested_index")

        if not index_spec or not index_spec.get("components"):
            return {
                **state,
                "index_result": {
                    "success": False,
                    "error": "No valid index design available"
                }
            }

        # Calculate the index
        result = calculate_index_from_spec(index_spec, self.db)

        logger.info(f"Index calculation: success={result.get('success')}")
        return {**state, "index_result": result}

    # =========================================================================
    # ANSWER GENERATION
    # =========================================================================

    def _node_generate_answer(self, state: AgentState) -> AgentState:
        """Generate final answer using LLM - handles all query types"""
        query_type = state.get("query_type", "single_dataset")
        user_query = self._get_last_user_message(state)
        districts_context = state.get("districts_context", "")

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)

        # Route to appropriate answer generation based on query type
        if query_type == "index_creation":
            return self._generate_index_answer(state, user_query, districts_context, llm)
        elif query_type == "multi_dataset":
            return self._generate_multi_answer(state, user_query, districts_context, llm)
        else:
            return self._generate_single_answer(state, user_query, districts_context, llm)

    def _generate_single_answer(
        self, state: AgentState, user_query: str, districts_context: str, llm
    ) -> AgentState:
        """Generate answer for single-dataset queries (original behavior)"""
        dataset = state.get("selected_dataset")
        analysis = state.get("analysis_result")

        system_prompt = (
            "You are a data analyst for the City of Munich Open Data Portal.\n"
            "You MUST NOT hallucinate data. Only use what's shown in the preview.\n"
            "If the data doesn't answer the question, say so explicitly.\n\n"
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

    def _generate_multi_answer(
        self, state: AgentState, user_query: str, districts_context: str, llm
    ) -> AgentState:
        """Generate answer for multi-dataset comparative queries"""
        combined_analysis = state.get("combined_analysis", "")
        analysis_results = state.get("analysis_results", [])
        selected_datasets = state.get("selected_datasets", [])

        system_prompt = (
            "You are a data analyst for the City of Munich Open Data Portal.\n"
            "You have analyzed multiple datasets to answer a comparative question.\n"
            "You MUST NOT hallucinate data. Only use what's provided.\n\n"
            "Instructions:\n"
            "- Summarize insights from the multi-dataset analysis\n"
            "- Highlight key comparisons and patterns\n"
            "- Use markdown tables when comparing data\n"
            "- Be concise but thorough\n"
        )

        if districts_context:
            system_prompt += f"\nMunich district reference:\n{districts_context}\n"

        # Build datasets summary
        datasets_text = "Datasets analyzed:\n"
        for ds in selected_datasets:
            datasets_text += f"- {ds.get('title', 'Unknown')}\n"

        # Include the pre-synthesized analysis
        analysis_text = combined_analysis if combined_analysis else "No combined analysis available."

        messages = [
            AIMessage(content=system_prompt),
            HumanMessage(content=(
                f"User question:\n{user_query}\n\n"
                f"{datasets_text}\n\n"
                f"Combined Analysis:\n{analysis_text}\n\n"
                "Provide a final answer based on this multi-dataset analysis."
            )),
        ]

        response = llm.invoke(messages)

        new_messages = list(state["messages"])
        new_messages.append(AIMessage(content=response.content))

        return {**state, "messages": new_messages}

    def _generate_index_answer(
        self, state: AgentState, user_query: str, districts_context: str, llm
    ) -> AgentState:
        """Generate answer for index creation queries"""
        index_spec = state.get("suggested_index", {})
        index_result = state.get("index_result", {})

        # Build pre-formatted tables that we'll append to the response
        top_table = ""
        bottom_table = ""
        stats_text = ""

        if index_result.get("success"):
            scores = index_result.get("scores", {})
            districts_info = index_result.get("districts", [])
            district_names = {d["number"]: d["name"] for d in districts_info}

            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

            # Build top 5 table
            top_table = "**Top 5 Districts:**\n\n"
            top_table += "| Rank | District | Score |\n"
            top_table += "|------|----------|-------|\n"
            for rank, (district_num, score) in enumerate(ranked[:5], 1):
                name = district_names.get(district_num, f"District {district_num}")
                top_table += f"| {rank} | {name} | {score:.1f} |\n"

            # Build bottom 5 table
            bottom_table = "\n**Bottom 5 Districts:**\n\n"
            bottom_table += "| Rank | District | Score |\n"
            bottom_table += "|------|----------|-------|\n"
            for rank, (district_num, score) in enumerate(ranked[-5:], len(ranked) - 4):
                name = district_names.get(district_num, f"District {district_num}")
                bottom_table += f"| {rank} | {name} | {score:.1f} |\n"

            stats = index_result.get("stats", {})
            stats_text = f"\n*Score range: {stats.get('min', 0):.1f} - {stats.get('max', 0):.1f}, Average: {stats.get('avg', 0):.1f}*"

        # Build context for LLM (just for explanation, not tables)
        system_prompt = (
            "You are a data analyst for the City of Munich Open Data Portal.\n"
            "You have created a composite index to rank Munich districts.\n"
            "Write a brief 2-3 sentence summary explaining:\n"
            "1. What the index measures\n"
            "2. Which district ranked highest and why\n"
            "3. Which district ranked lowest\n\n"
            "DO NOT include any tables or rankings in your response - those will be added separately.\n"
            "Keep your response under 100 words.\n"
        )

        # Build index info for context
        index_text = f"Index: {index_spec.get('name', 'Custom Index')}\n"
        index_text += f"Description: {index_spec.get('description', '')}\n\n"

        index_text += "Components used:\n"
        for comp in index_spec.get("components", []):
            weight_sign = "+" if comp.get("weight", 0) >= 0 else ""
            index_text += f"- {comp.get('label', comp.get('dataset_pattern'))}: weight={weight_sign}{comp.get('weight', 0)}\n"

        if index_result.get("success"):
            scores = index_result.get("scores", {})
            districts_info = index_result.get("districts", [])
            district_names = {d["number"]: d["name"] for d in districts_info}
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

            index_text += f"\nTop district: {district_names.get(ranked[0][0])} ({ranked[0][1]:.1f})\n"
            index_text += f"Bottom district: {district_names.get(ranked[-1][0])} ({ranked[-1][1]:.1f})\n"

        messages = [
            AIMessage(content=system_prompt),
            HumanMessage(content=(
                f"User question: {user_query}\n\n"
                f"Index data:\n{index_text}\n\n"
                "Write a brief summary (no tables)."
            )),
        ]

        response = llm.invoke(messages)

        # Combine LLM summary with pre-formatted tables
        final_response = f"## {index_spec.get('name', 'Custom Index')}\n\n"
        final_response += response.content.strip() + "\n\n"
        final_response += top_table
        final_response += bottom_table
        final_response += stats_text

        new_messages = list(state["messages"])
        new_messages.append(AIMessage(content=final_response))

        return {**state, "messages": new_messages}


# Convenience function
def build_graph():
    """Build and return a compiled LangGraph (for legacy compatibility)"""
    agent = ChatAgent()
    return agent.graph
