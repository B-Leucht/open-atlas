"""
FastAPI application for the Munich Open Data Chatbot.

This API exposes the same agent functionality as the Streamlit app,
but through REST endpoints instead of a web UI.
"""

import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

from src.agent import AgentState, build_graph

load_dotenv()

app = FastAPI(
    title="Munich Open Data Chatbot API",
    description="Ask questions about datasets from the Munich Open Data portal. "
    "The agent finds a relevant dataset and analyzes it without hallucinating.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins (change to ["http://localhost:3000"] for production)
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, OPTIONS, etc.)
    allow_headers=["*"],  # Allows all headers
)


@lru_cache()
def get_graph():
    """Get the compiled LangGraph agent (cached for performance)."""
    return build_graph()


class QueryRequest(BaseModel):
    """Request model for a user query."""

    query: str
    conversation_id: Optional[str] = None


class QueryResponse(BaseModel):
    """Response model for a query."""

    answer: str
    conversation_id: Optional[str] = None


@app.get("/")
def root():
    """Root endpoint with API information."""
    return {
        "name": "Munich Open Data Chatbot API",
        "description": "Ask questions about datasets from the Munich Open Data portal",
        "version": "1.0.0",
        "endpoints": {
            "/query": "POST - Submit a natural language query about Munich open data",
            "/health": "GET - Health check endpoint",
        },
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    try:
        # Verify the graph can be loaded
        graph = get_graph()
        return {"status": "healthy", "graph_loaded": graph is not None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    """
    Submit a natural language query about Munich open data.

    The agent will:
    1. Search the catalog for relevant datasets
    2. Select the best dataset and resource
    3. Execute appropriate analysis (CSV or geospatial)
    4. Generate a natural language answer

    Args:
        request: QueryRequest containing the user's question

    Returns:
        QueryResponse with the agent's answer
    """
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    try:
        graph = get_graph()

        # Build initial graph state (same as Streamlit app)
        state: AgentState = {
            "messages": [HumanMessage(content=request.query)],
            "selected_dataset": None,
            "analysis_result": None,
        }

        # Invoke the graph (same as Streamlit app)
        final_state = graph.invoke(state)

        # Extract the final AI message (same as Streamlit app)
        messages = final_state["messages"]
        last_ai = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                last_ai = msg
                break

        answer = last_ai.content if last_ai else "I could not generate an answer."

        return QueryResponse(
            answer=answer,
            conversation_id=request.conversation_id,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing query: {str(e)}",
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

