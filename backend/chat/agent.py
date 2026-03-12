"""
LLM Agent for Munich Open Data analysis
Uses LangGraph for workflow, DuckDB for SQL execution
Integrates with data layer for districts and cached datasets
Supports conversation history via LangGraph checkpointing
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

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

# ---------------------------------------------------------------------------
# Feature flag: set to True to use the autonomous two-node ReAct agent.
# False (default) keeps the original deterministic DAG pipeline.
# ---------------------------------------------------------------------------
USE_AGENTIC_GRAPH = True

# ---------------------------------------------------------------------------
# System prompt for the agentic graph
# ---------------------------------------------------------------------------
AGENTIC_SYSTEM_PROMPT = """You are an AI assistant for the Munich Open Data Portal (Open Atlas).
You help users explore and analyze Munich's public datasets across 25 city districts (Stadtbezirke).

Available data topics include: parks, schools, playgrounds, hospitals, cycling infrastructure,
kindergartens (Kitas), senior centers, recycling stations, cultural venues, public transport,
traffic safety, green spaces, and more.

How to answer questions:
1. Call search_datasets to discover what relevant data exists.
2. Call analyze_dataset to run a SQL query on the data and get results.
3. For district ranking or scoring questions ("best/worst district for X", "rank districts by Y"),
   call calculate_district_index instead.
4. Generate a clear, concise answer using only what the data shows.

Rules:
- Never invent numbers or facts — only state what the datasets actually contain.
- If no relevant dataset exists for a question, say so clearly.
- For follow-up questions, use context already in the conversation history.
- When results contain location data, mention that they will appear on the map.
- Use calculate_district_index directly for any ranking/scoring question — it selects its own data, do NOT call search_datasets first.

{districts_context}"""


# ===========================================================================
# TTL-based memory store wrapper
# ===========================================================================

class TTLMemoryStore:
    """
    Memory store wrapper with TTL-based cleanup to prevent unbounded memory growth.
    Conversations expire after a configurable TTL (default 1 hour).
    """

    def __init__(self, ttl_seconds: int = 3600, cleanup_interval: int = 300):
        self._store = MemorySaver()
        self._access_times: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()

    @property
    def saver(self) -> MemorySaver:
        self._maybe_cleanup()
        return self._store

    def touch(self, thread_id: str):
        with self._lock:
            self._access_times[thread_id] = time.time()

    def _maybe_cleanup(self):
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        with self._lock:
            self._last_cleanup = now
            expired = [tid for tid, t in self._access_times.items() if now - t > self._ttl]

            for thread_id in expired:
                del self._access_times[thread_id]

            if expired:
                logger.info(f"Cleaned up {len(expired)} expired conversation threads")

            if len(self._access_times) == 0:
                logger.info("All threads expired, recreating memory store")
                self._store = MemorySaver()

    def clear_all(self):
        with self._lock:
            self._store = MemorySaver()
            self._access_times.clear()
            logger.info("Cleared all conversation memory")

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            active = sum(1 for t in self._access_times.values() if now - t < self._ttl)
            return {
                "total_threads": len(self._access_times),
                "active_threads": active,
                "ttl_seconds": self._ttl,
            }


# Global memory store (1 hour TTL, cleanup every 5 minutes)
_memory_store = TTLMemoryStore(ttl_seconds=3600, cleanup_interval=300)


# ===========================================================================
# LangGraph state
# ===========================================================================

class AgentState(TypedDict):
    """LangGraph state for the data analysis agent"""

    # add_messages reducer: nodes append new messages rather than replacing the list.
    # This makes MemorySaver checkpointing work correctly across conversation turns.
    messages: Annotated[List[BaseMessage], add_messages]

    # Static context injected once per query
    districts_context: Optional[str]

    # ---- Legacy DAG path fields ----
    query_type: Optional[str]           # "single_dataset" | "multi_dataset" | "index_creation"
    selected_dataset: Optional[Dict[str, Any]]
    analysis_result: Optional[Dict[str, Any]]
    selected_datasets: List[Dict[str, Any]]
    analysis_results: List[Dict[str, Any]]
    combined_analysis: Optional[str]

    # ---- Shared output side-channels (populated by both paths) ----
    suggested_index: Optional[Dict[str, Any]]
    index_result: Optional[Dict[str, Any]]
    geo_data: Optional[Dict[str, Any]]  # Agentic path writes here; legacy constructs in query()


# ===========================================================================
# Chat Agent
# ===========================================================================

class ChatAgent:
    """
    LLM-powered agent for analyzing Munich Open Data.

    Two graph modes (controlled by USE_AGENTIC_GRAPH):
    - False (default): deterministic 8-node DAG with classify → route → analyze → answer
    - True: autonomous 2-node ReAct cycle where the LLM calls tools and iterates
    """

    def __init__(self, db=None, vector_store: VectorStore = None):
        self.db = db
        self.vector_store = vector_store or VectorStore()
        self._graph = None
        self._districts_cache = None
        # Agentic path components (lazy-initialized)
        self._tools: Optional[list] = None
        self._llm_with_tools = None
        self._tool_map: Optional[Dict[str, Any]] = None

    @property
    def graph(self):
        if self._graph is None:
            self._graph = self._build_graph()
        return self._graph

    def get_districts_context(self) -> str:
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

    # =========================================================================
    # Public query interface
    # =========================================================================

    def query(self, user_query: str, thread_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Process a user query and return a structured response.

        Args:
            user_query: The user's question
            thread_id: Conversation thread ID for history. Created if not provided.

        Returns:
            {
                "answer": str,
                "query_type": str,
                "thread_id": str,
                "index_result": Optional[Dict],
                "suggested_index": Optional[Dict],
                "geo_data": Optional[Dict],
            }
        """
        if not thread_id:
            thread_id = str(uuid.uuid4())

        # With add_messages reducer, we pass only the NEW message.
        # LangGraph appends it to the checkpoint history for the thread.
        base_state: AgentState = {
            "messages": [HumanMessage(content=user_query)],
            "districts_context": self.get_districts_context(),
            # Reset output side-channels for every new query
            "geo_data": None,
            "index_result": None,
            "suggested_index": None,
        }

        # Legacy path also needs its per-query fields reset
        if not USE_AGENTIC_GRAPH:
            base_state.update({
                "query_type": None,
                "selected_dataset": None,
                "analysis_result": None,
                "selected_datasets": [],
                "analysis_results": [],
                "combined_analysis": None,
            })

        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 12,  # caps the agentic loop at 6 tool-call cycles
        }
        _memory_store.touch(thread_id)

        final_state = self.graph.invoke(base_state, config)

        # Extract the final assistant message (skip intermediate tool-calling turns)
        answer = "I could not generate an answer."
        for msg in reversed(final_state["messages"]):
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                answer = msg.content
                break

        response = {
            "answer": answer,
            "query_type": final_state.get("query_type", "agentic" if USE_AGENTIC_GRAPH else "single_dataset"),
            "thread_id": thread_id,
        }

        if USE_AGENTIC_GRAPH:
            # Agentic path: side-channels populated by the tool executor node
            if final_state.get("index_result", {}) and final_state["index_result"].get("success"):
                response["index_result"] = final_state["index_result"]
                response["suggested_index"] = final_state.get("suggested_index")
            if final_state.get("geo_data"):
                response["geo_data"] = final_state["geo_data"]
        else:
            # Legacy path: index data
            if final_state.get("query_type") == "index_creation":
                index_result = final_state.get("index_result")
                if index_result and index_result.get("success"):
                    response["index_result"] = index_result
                    response["suggested_index"] = final_state.get("suggested_index")

            # Legacy path: construct geo_data from analysis state
            analysis_result = final_state.get("analysis_result")
            selected_dataset = final_state.get("selected_dataset")
            if analysis_result and selected_dataset:
                dataset_id = selected_dataset.get("id")
                coords = analysis_result.get("coordinates")
                has_geo = coords is not None or analysis_result.get("kind") == "geospatial"
                if has_geo and dataset_id:
                    response["geo_data"] = {
                        "type": "dataset",
                        "dataset_id": dataset_id,
                        "dataset_title": selected_dataset.get("title"),
                        "fallback_coordinates": coords,
                    }
                    logger.info(f"geo_data: dataset_id={dataset_id}, coords={len(coords) if coords else 0}")

        return response

    def query_text(self, user_query: str) -> str:
        """Return just the answer text. For backward compatibility."""
        return self.query(user_query).get("answer", "I could not generate an answer.")

    # =========================================================================
    # Graph construction
    # =========================================================================

    def _build_graph(self):
        if USE_AGENTIC_GRAPH:
            return self._build_agentic_graph()
        return self._build_legacy_graph()

    # ---- Agentic graph (2-node ReAct cycle) ---------------------------------

    def _setup_agentic_components(self):
        """Lazy-initialize LLM binding and tool registry for the agentic path."""
        if self._tools is not None:
            return
        self._tools = self._create_tools()
        llm = ChatOpenAI(model="gpt-5-mini", temperature=0.1)
        self._llm_with_tools = llm.bind_tools(self._tools)
        self._tool_map = {t.name: t for t in self._tools}

    def _create_tools(self) -> list:
        """
        Create LangChain tools that close over the agent's dependencies.
        Returns a list ready for llm.bind_tools().
        """
        vector_store = self.vector_store
        agent_ref = self  # gives closures access to self.db

        def _resolve_dataset(dataset_id: str) -> Optional[Dict[str, Any]]:
            """Look up a dataset by ID in the vector store, returning metadata + resources."""
            try:
                collection = vector_store.get_collection()
                result = collection.get(ids=[dataset_id], include=["metadatas"])
                if result and result.get("metadatas"):
                    meta = result["metadatas"][0]
                    raw = meta.get("resources", "[]")
                    resources = json.loads(raw) if isinstance(raw, str) else (raw or [])
                    return {
                        "id": meta.get("id", dataset_id),
                        "title": meta.get("title", "Unknown"),
                        "description": meta.get("description", ""),
                        "resources": resources,
                    }
            except Exception as e:
                logger.warning(f"Could not resolve dataset '{dataset_id}': {e}")
            return None

        @tool
        def search_datasets(query: str, n_results: int = 5) -> str:
            """Search the Munich Open Data catalog by semantic similarity.
            Returns dataset IDs, titles, and relevance scores (0–1).
            Use the returned IDs directly with analyze_dataset.
            If results have low relevance (score < 0.4), retry with a more specific query before analyzing.

            Args:
                query: Natural language description of the topic or data type to find
                    (e.g. "playgrounds", "cycling lanes per district", "hospital locations").
                n_results: How many results to return (1–10, default 5). Increase if the
                    first result looks wrong or irrelevant.
            """
            hits = vector_store.search(query, n_results=min(max(n_results, 1), 10))
            if not hits:
                return "No datasets found for that query in the Munich Open Data catalog."

            lines = [f"Found {len(hits)} datasets:\n"]
            for i, hit in enumerate(hits, 1):
                sim = hit.get("_similarity", 0)
                relevance = "high" if sim > 0.7 else "medium" if sim > 0.4 else "low"
                lines.append(f"{i}. ID: {hit['id']}")
                lines.append(f"   Title: {hit['title']}")
                lines.append(f"   Relevance: {relevance} ({sim:.2f})")
                if hit.get("description"):
                    lines.append(f"   {hit['description'][:250]}")
                lines.append("")
            return "\n".join(lines)

        @tool
        def analyze_dataset(dataset_id: str, question: str) -> str:
            """Download and run SQL analysis on a single Munich Open Data dataset.
            Best for: listing items, filtering by location or attribute, counting,
            grouping by a non-district column, showing raw data.
            Not for: ranking all 25 districts by a composite score — use
            calculate_district_index for that instead.
            Returns a markdown table of up to 200 rows. If the dataset contains
            location data it will be shown on the map automatically.

            Args:
                dataset_id: ID from search_datasets results.
                question: Specific analytical question, e.g. "How many playgrounds are
                    in each district?", "List all parks in Schwabing", "Show top 10 by area".
                    The more specific the question, the better the generated SQL.
            """
            dataset = _resolve_dataset(dataset_id)
            if not dataset:
                return f"Dataset '{dataset_id}' not found. Call search_datasets to get valid IDs."

            resource = select_best_resource(dataset.get("resources", []))
            if not resource or not resource.get("url"):
                return f"Dataset '{dataset.get('title', dataset_id)}' has no downloadable resource."

            fmt = (resource.get("format") or "").upper()
            url = resource["url"]

            if fmt == "CSV":
                result = analyze_csv(url, question)
            elif fmt in {"GEOJSON", "WFS", "JSON"}:
                result = analyze_geospatial(url, question)
            else:
                return f"Format '{fmt}' is not supported for analysis. Try a different dataset."

            if result.get("error"):
                return (
                    f"Analysis failed for '{dataset['title']}': "
                    f"{result.get('error_message', 'Unknown error')}"
                )

            content = result.get("content", f"Rows: {result.get('row_count', 0)}\n{result.get('preview_markdown', '')}")

            # Pack geo_data as a structured marker so the tool executor can
            # extract it into state without the LLM seeing the raw JSON.
            coords = result.get("coordinates")
            if coords or result.get("kind") == "geospatial":
                geo_data = {
                    "type": "dataset",
                    "dataset_id": dataset_id,
                    "dataset_title": dataset.get("title", ""),
                    "fallback_coordinates": coords,
                }
                marker = json.dumps({"_geo_data": geo_data})
                content += f"\n__STRUCTURED__:{marker}__END__"

            return content

        @tool
        def calculate_district_index(query: str) -> str:
            """Automatically select relevant datasets and compute a composite score to
            rank all 25 Munich districts. This tool handles its own dataset discovery —
            do NOT call search_datasets first, it is not needed.
            Use for: "Which district is best for X?", "Rank districts by Y",
            "Score districts for Z residents", "best/worst district for ...".
            Results are displayed on the choropleth map. This operation takes 10–20 seconds.

            Args:
                query: The full ranking question or dimension using the user's original
                    phrasing, e.g. "best district for families with young children" or
                    "cycling infrastructure quality". The exact wording drives dataset
                    selection, so do not trim or rephrase it.
            """
            if agent_ref.db is None:
                from data.database import Database
                agent_ref.db = Database()

            from data.indices import IndexCalculator
            calculator = IndexCalculator(agent_ref.db)
            available_datasets = calculator.get_available_datasets()

            index_spec = design_index(query, available_datasets)
            if not index_spec.get("components"):
                return "Could not design a meaningful index for that query. Try rephrasing."

            result = calculate_index_from_spec(index_spec, agent_ref.db)
            if not result.get("success"):
                return f"Index calculation failed: {result.get('error', 'Unknown error')}"

            scores = result.get("scores", {})
            districts_info = result.get("districts", [])
            district_names = {d["number"]: d["name"] for d in districts_info}
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

            lines = [
                f"## {index_spec.get('name', 'District Index')}\n",
                f"{index_spec.get('description', '')}\n",
                "| Rank | District | Score |",
                "|------|----------|-------|",
            ]
            for rank, (num, score) in enumerate(ranked, 1):
                name = district_names.get(num, f"District {num}")
                lines.append(f"| {rank} | {name} | {score:.1f} |")

            stats = result.get("stats", {})
            lines.append(
                f"\n*Range: {stats.get('min', 0):.1f}–{stats.get('max', 0):.1f}, "
                f"Avg: {stats.get('avg', 0):.1f}*"
            )
            lines.append(f"\n**Methodology:** {index_spec.get('reasoning', '')}")

            content = "\n".join(lines)

            # Pack index result as a structured marker for the tool executor
            structured = {
                "_index_result": result,
                "_suggested_index": index_spec,
            }
            content += f"\n__STRUCTURED__:{json.dumps(structured)}__END__"

            return content

        return [search_datasets, analyze_dataset, calculate_district_index]

    def _build_agentic_graph(self):
        self._setup_agentic_components()
        graph = StateGraph(AgentState)
        graph.add_node("agent", self._node_agent)
        graph.add_node("tools", self._node_execute_tools)
        graph.set_entry_point("agent")
        graph.add_conditional_edges(
            "agent",
            self._should_continue,
            {"tools": "tools", END: END},
        )
        graph.add_edge("tools", "agent")
        return graph.compile(checkpointer=_memory_store.saver)

    def _should_continue(self, state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tools"
        return END

    def _node_agent(self, state: AgentState) -> Dict[str, Any]:
        """Invoke the LLM with the full message history. Returns new messages only."""
        messages = list(state["messages"])

        # Inject the system message once at the start of a thread.
        # Because add_messages deduplicates by ID, re-injecting on subsequent turns
        # is harmless, but we skip it when it's already present to save tokens.
        if not any(isinstance(m, SystemMessage) for m in messages):
            system = SystemMessage(
                content=AGENTIC_SYSTEM_PROMPT.format(
                    districts_context=state.get("districts_context", "")
                )
            )
            messages = [system] + messages

        response = self._llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def _node_execute_tools(self, state: AgentState) -> Dict[str, Any]:
        """Execute every tool call in the last AIMessage. Returns new messages + side-channel updates."""
        last = state["messages"][-1]
        tool_messages: List[ToolMessage] = []
        updates: Dict[str, Any] = {}

        for tc in getattr(last, "tool_calls", []):
            tool_name = tc["name"]
            tool_args = tc["args"]
            tc_id = tc["id"]

            try:
                tool_fn = self._tool_map.get(tool_name)
                if tool_fn is None:
                    raise ValueError(f"Unknown tool: {tool_name}")

                raw = tool_fn.invoke(tool_args)

                # Strip the structured side-channel marker before sending to LLM
                content = raw
                if isinstance(raw, str) and "__STRUCTURED__:" in raw:
                    parts = raw.split("__STRUCTURED__:", 1)
                    content = parts[0].strip()
                    try:
                        struct_json = parts[1].replace("__END__", "").strip()
                        structured = json.loads(struct_json)
                        if structured.get("_geo_data"):
                            updates["geo_data"] = structured["_geo_data"]
                        if structured.get("_index_result"):
                            updates["index_result"] = structured["_index_result"]
                            updates["suggested_index"] = structured.get("_suggested_index")
                    except Exception as parse_err:
                        logger.warning(f"Could not parse structured marker: {parse_err}")

                tool_messages.append(ToolMessage(content=content, tool_call_id=tc_id))

            except Exception as e:
                logger.error(f"Tool '{tool_name}' raised: {e}")
                tool_messages.append(
                    ToolMessage(
                        content=f"Tool '{tool_name}' failed: {e}. Try a different approach.",
                        tool_call_id=tc_id,
                    )
                )

        updates["messages"] = tool_messages
        return updates

    # =========================================================================
    # Legacy DAG graph (original deterministic pipeline)
    # =========================================================================

    def _build_legacy_graph(self):
        graph = StateGraph(AgentState)

        graph.add_node("classify_query", self._node_classify_query)
        graph.add_node("single_lookup", self._node_lookup_dataset)
        graph.add_node("execute_tool", self._node_execute_tool)
        graph.add_node("multi_lookup", self._node_lookup_datasets)
        graph.add_node("analyze_multi", self._node_analyze_multi)
        graph.add_node("design_index", self._node_design_index)
        graph.add_node("calculate_index", self._node_calculate_index)
        graph.add_node("generate_answer", self._node_generate_answer)

        graph.set_entry_point("classify_query")

        graph.add_conditional_edges(
            "classify_query",
            self._route_by_query_type,
            {
                "single_lookup": "single_lookup",
                "multi_lookup": "multi_lookup",
                "design_index": "design_index",
            },
        )

        graph.add_edge("single_lookup", "execute_tool")
        graph.add_edge("execute_tool", "generate_answer")
        graph.add_edge("multi_lookup", "analyze_multi")
        graph.add_edge("analyze_multi", "generate_answer")
        graph.add_edge("design_index", "calculate_index")
        graph.add_edge("calculate_index", "generate_answer")
        graph.add_edge("generate_answer", END)

        return graph.compile(checkpointer=_memory_store.saver)

    # ---- Helpers ------------------------------------------------------------

    def _get_last_user_message(self, state: AgentState) -> str:
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                return msg.content if isinstance(msg.content, str) else str(msg.content)
        return ""

    def _prepare_dataset(self, hit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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

    # ---- Classification node ------------------------------------------------

    def _node_classify_query(self, state: AgentState) -> Dict[str, Any]:
        user_query = self._get_last_user_message(state)
        classification = classify_query(user_query)
        logger.info(f"Query classified as: {classification}")
        return {"query_type": classification.get("query_type", "single_dataset")}

    def _route_by_query_type(self, state: AgentState) -> str:
        route_map = {
            "single_dataset": "single_lookup",
            "multi_dataset": "multi_lookup",
            "index_creation": "design_index",
        }
        return route_map.get(state.get("query_type", "single_dataset"), "single_lookup")

    # ---- Single-dataset path ------------------------------------------------

    def _node_lookup_dataset(self, state: AgentState) -> Dict[str, Any]:
        user_query = self._get_last_user_message(state)
        hits = self.vector_store.search(user_query, n_results=3)
        if not hits:
            return {"selected_dataset": None}

        primary = hits[0]
        raw_resources = primary.get("resources") or "[]"
        if isinstance(raw_resources, str):
            try:
                resources = json.loads(raw_resources)
            except json.JSONDecodeError:
                resources = []
        else:
            resources = raw_resources or []

        return {
            "selected_dataset": {
                "id": primary.get("id"),
                "title": primary.get("title"),
                "description": primary.get("description"),
                "resources": resources,
                "selected_resource": select_best_resource(resources),
            }
        }

    def _node_execute_tool(self, state: AgentState) -> Dict[str, Any]:
        dataset = state.get("selected_dataset")
        if not dataset:
            return {"analysis_result": None}

        selected_resource = dataset.get("selected_resource") or {}
        fmt = (selected_resource.get("format") or "").upper()
        url = selected_resource.get("url")
        user_query = self._get_last_user_message(state)

        logger.info(
            f"execute_tool: dataset='{dataset.get('title')}', "
            f"format='{fmt}', url={url[:80] if url else 'None'}..."
        )

        if not url:
            analysis_result = {"error": "no_resource_url", "error_message": "Dataset found but no usable file URL."}
        elif fmt == "CSV":
            analysis_result = analyze_csv(url, user_query)
        elif fmt in {"GEOJSON", "WFS", "JSON"}:
            analysis_result = analyze_geospatial(url, user_query)
        else:
            analysis_result = {"error": "unsupported_format", "error_message": f"Format '{fmt}' is not yet supported."}

        logger.info(
            f"Analysis complete: kind={analysis_result.get('kind')}, "
            f"coords={analysis_result.get('coordinates') is not None}"
        )
        return {"analysis_result": analysis_result}

    # ---- Multi-dataset path -------------------------------------------------

    def _node_lookup_datasets(self, state: AgentState) -> Dict[str, Any]:
        user_query = self._get_last_user_message(state)
        hits = self.vector_store.search(user_query, n_results=10)
        if not hits:
            return {"selected_datasets": []}
        datasets = [d for hit in hits if (d := self._prepare_dataset(hit))]
        logger.info(f"Multi-dataset lookup: {len(datasets)} datasets")
        return {"selected_datasets": datasets}

    def _node_analyze_multi(self, state: AgentState) -> Dict[str, Any]:
        datasets = state.get("selected_datasets", [])
        user_query = self._get_last_user_message(state)
        if not datasets:
            return {"analysis_results": [], "combined_analysis": "No datasets found for analysis."}
        result = analyze_multiple_datasets(datasets, user_query)
        return {
            "analysis_results": result.get("individual_results", []),
            "combined_analysis": result.get("combined_analysis", ""),
        }

    # ---- Index creation path ------------------------------------------------

    def _node_design_index(self, state: AgentState) -> Dict[str, Any]:
        user_query = self._get_last_user_message(state)
        if self.db is None:
            from data.database import Database
            self.db = Database()
        from data.indices import IndexCalculator
        available_datasets = IndexCalculator(self.db).get_available_datasets()
        index_spec = design_index(user_query, available_datasets)
        logger.info(f"Designed index '{index_spec.get('name')}' with {len(index_spec.get('components', []))} components")
        return {"suggested_index": index_spec}

    def _node_calculate_index(self, state: AgentState) -> Dict[str, Any]:
        index_spec = state.get("suggested_index")
        if not index_spec or not index_spec.get("components"):
            return {"index_result": {"success": False, "error": "No valid index design available"}}
        result = calculate_index_from_spec(index_spec, self.db)
        logger.info(f"Index calculation: success={result.get('success')}")
        return {"index_result": result}

    # =========================================================================
    # Legacy answer generation (shared across all three DAG paths)
    # =========================================================================

    def _node_generate_answer(self, state: AgentState) -> Dict[str, Any]:
        query_type = state.get("query_type", "single_dataset")
        user_query = self._get_last_user_message(state)
        districts_context = state.get("districts_context", "")
        llm = ChatOpenAI(model="gpt-5-mini", temperature=0.1)

        if query_type == "index_creation":
            return self._generate_index_answer(state, user_query, districts_context, llm)
        elif query_type == "multi_dataset":
            return self._generate_multi_answer(state, user_query, districts_context, llm)
        else:
            return self._generate_single_answer(state, user_query, districts_context, llm)

    def _generate_single_answer(self, state, user_query, districts_context, llm) -> Dict[str, Any]:
        dataset = state.get("selected_dataset")
        analysis = state.get("analysis_result")

        data_table = ""
        if analysis and not analysis.get("error"):
            preview_md = analysis.get("preview_markdown", "")
            row_count = analysis.get("row_count", 0)
            if preview_md:
                data_table = f"\n\n**Data ({row_count} rows):**\n\n{preview_md}\n"

        system_prompt = (
            "You are a data analyst for the City of Munich Open Data Portal.\n"
            "You MUST NOT hallucinate data. Only use what's provided in the analysis.\n"
            "If the data doesn't answer the question, say so explicitly.\n\n"
            "Instructions:\n"
            "- Write a brief 2-4 sentence summary answering the user's question.\n"
            "- Use the 'Total rows in result' count to describe how many items were found.\n"
            "- If locations are being displayed on the map, mention this in your response.\n"
            "- Focus on key insights from the data.\n"
            "- DO NOT include any tables in your response — tables will be added automatically.\n"
            "- DO NOT list out all the data points — just summarize the main findings.\n"
            "- Keep your response under 100 words.\n"
        )
        if districts_context:
            system_prompt += f"\nMunich district reference:\n{districts_context}\n"

        dataset_text = "No dataset found."
        dataset_title = "Unknown Dataset"
        if dataset:
            dataset_title = dataset.get("title", "Unknown Dataset")
            dataset_text = f"Dataset: {dataset_title}\n"
            dataset_text += f"Description: {dataset.get('description', '')[:500]}\n"
            res = dataset.get("selected_resource") or {}
            if res:
                dataset_text += f"Resource: {res.get('name')} ({res.get('format')})\n"

        analysis_context = "No analysis available."
        if analysis:
            if analysis.get("error"):
                analysis_context = f"Error: {analysis.get('error_message')}"
            else:
                row_count = analysis.get("row_count", 0)
                coords = analysis.get("coordinates", [])
                coords_count = len(coords) if coords else 0
                analysis_context = f"SQL: {analysis.get('sql_query', 'N/A')}\n"
                analysis_context += f"Total rows in result: {row_count}\n"
                analysis_context += f"Columns: {', '.join(analysis.get('columns', []))}\n"
                if coords_count > 0:
                    analysis_context += f"Map visualization: {coords_count} locations will be displayed on the map.\n"
                preview_md = analysis.get("preview_markdown", "")
                if preview_md:
                    analysis_context += f"Data preview (showing up to 200 rows):\n{preview_md[:2000]}"

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"User question:\n{user_query}\n\n"
                f"Dataset:\n{dataset_text}\n\n"
                f"Analysis:\n{analysis_context}\n\n"
                "Write a brief summary (no tables)."
            )),
        ]

        response = llm.invoke(messages)
        final_response = f"## {dataset_title}\n\n{response.content.strip()}{data_table}"
        return {"messages": [AIMessage(content=final_response)]}

    def _generate_multi_answer(self, state, user_query, districts_context, llm) -> Dict[str, Any]:
        combined_analysis = state.get("combined_analysis", "")
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

        datasets_text = "Datasets analyzed:\n" + "".join(
            f"- {ds.get('title', 'Unknown')}\n" for ds in selected_datasets
        )
        analysis_text = combined_analysis or "No combined analysis available."

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"User question:\n{user_query}\n\n"
                f"{datasets_text}\n\n"
                f"Combined Analysis:\n{analysis_text}\n\n"
                "Provide a final answer based on this multi-dataset analysis."
            )),
        ]

        response = llm.invoke(messages)
        return {"messages": [AIMessage(content=response.content)]}

    def _generate_index_answer(self, state, user_query, districts_context, llm) -> Dict[str, Any]:
        index_spec = state.get("suggested_index", {})
        index_result = state.get("index_result", {})

        top_table = ""
        bottom_table = ""
        stats_text = ""

        if index_result.get("success"):
            scores = index_result.get("scores", {})
            districts_info = index_result.get("districts", [])
            district_names = {d["number"]: d["name"] for d in districts_info}
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

            top_table = "**Top 5 Districts:**\n\n| Rank | District | Score |\n|------|----------|-------|\n"
            for rank, (num, score) in enumerate(ranked[:5], 1):
                top_table += f"| {rank} | {district_names.get(num, f'District {num}')} | {score:.1f} |\n"

            bottom_table = "\n**Bottom 5 Districts:**\n\n| Rank | District | Score |\n|------|----------|-------|\n"
            for rank, (num, score) in enumerate(ranked[-5:], len(ranked) - 4):
                bottom_table += f"| {rank} | {district_names.get(num, f'District {num}')} | {score:.1f} |\n"

            stats = index_result.get("stats", {})
            stats_text = f"\n*Score range: {stats.get('min', 0):.1f}–{stats.get('max', 0):.1f}, Average: {stats.get('avg', 0):.1f}*"

        system_prompt = (
            "You are a data analyst for the City of Munich Open Data Portal.\n"
            "You have created a composite index to rank Munich districts.\n"
            "Write a brief 2-3 sentence summary explaining:\n"
            "1. What the index measures\n"
            "2. Which district ranked highest and why\n"
            "3. Which district ranked lowest\n\n"
            "DO NOT include any tables or rankings — those will be added separately.\n"
            "Keep your response under 100 words.\n"
        )

        index_text = f"Index: {index_spec.get('name', 'Custom Index')}\n"
        index_text += f"Description: {index_spec.get('description', '')}\n\nComponents:\n"
        for comp in index_spec.get("components", []):
            sign = "+" if comp.get("weight", 0) >= 0 else ""
            index_text += f"- {comp.get('label', comp.get('dataset_pattern'))}: weight={sign}{comp.get('weight', 0)}\n"

        if index_result.get("success"):
            scores = index_result.get("scores", {})
            districts_info = index_result.get("districts", [])
            district_names = {d["number"]: d["name"] for d in districts_info}
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            index_text += f"\nTop: {district_names.get(ranked[0][0])} ({ranked[0][1]:.1f})"
            index_text += f"\nBottom: {district_names.get(ranked[-1][0])} ({ranked[-1][1]:.1f})"

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"User question: {user_query}\n\nIndex data:\n{index_text}\n\nWrite a brief summary (no tables)."
            )),
        ]

        response = llm.invoke(messages)
        final_response = (
            f"## {index_spec.get('name', 'Custom Index')}\n\n"
            f"{response.content.strip()}\n\n"
            f"{top_table}{bottom_table}{stats_text}"
        )
        return {"messages": [AIMessage(content=final_response)]}


# Convenience function (backward compatibility)
def build_graph():
    return ChatAgent().graph
