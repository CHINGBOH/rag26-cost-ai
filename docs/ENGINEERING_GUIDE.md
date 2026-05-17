# Engineering Guide

## Repository Philosophy

This repository is evolving from a standalone RAG project into a long-term AI operating system for:

- RAG orchestration
- Agent workflows
- Context engineering
- OCR pipelines
- Memory systems
- Medical / enterprise AI applications

The goal is to keep the system modular, observable, and production-oriented.

---

## Recommended Architecture Layers

```text
apps/          # Product applications
core/          # AI engine and orchestration
infra/         # Deployment and infrastructure
prompts/       # Prompt assets
experiments/   # Temporary experiments
archive/       # Deprecated modules
```

---

## Core Engineering Principles

### 1. Context First

The system is designed around context flow:

- retrieval context
- memory context
- workflow state
- tool state
- session history

### 2. Ports & Adapters

Business logic should depend on interfaces, not infrastructure.

### 3. Config Driven

Infrastructure switching should happen through configuration only.

### 4. Long-Term Maintainability

Avoid:

- hardcoded prompts
- direct vendor coupling
- duplicated pipelines
- fragmented repositories

---

## Future Core Modules

```text
core/
├── agents/
├── rag/
├── memory/
├── workflows/
├── prompts/
├── tools/
├── embeddings/
└── evaluators/
```

---

## Repository Governance

### experiments/

Short-lived tests and prototypes.

### archive/

Deprecated systems or historical implementations.

### apps/

Business-facing applications:

- medical-ai
- crm
- admin
- chat-ui

---

## Recommended Toolchain

- uv
- Docker Compose
- Ruff
- Black
- Pytest
- LangGraph
- FastAPI

---

## Long-Term Direction

This repository is expected to evolve into:

- AI workflow platform
- Agent operating system
- Enterprise-grade RAG infrastructure
- Medical/industry AI orchestration system
