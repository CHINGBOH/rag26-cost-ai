-- =============================================================================
-- RAG Dashboard - Postgres baseline schema
-- Source: production server (1.12.242.193) pg_dump -s
-- Generated: see issue #153
-- DO NOT EDIT MANUALLY. Regenerate via scripts/dump-prod-schema.sh
-- =============================================================================

--
-- PostgreSQL database dump
--


-- Dumped from database version 16.13 (Debian 16.13-1.pgdg12+1)
-- Dumped by pg_dump version 16.13 (Debian 16.13-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: zhparser; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS zhparser WITH SCHEMA public;


--
-- Name: EXTENSION zhparser; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION zhparser IS 'a parser for full-text search of Chinese';


--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: canonical_concepts_tsv_trigger(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.canonical_concepts_tsv_trigger() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.tsv := to_tsvector('chinese',
                   coalesce(NEW.concept_name, '') || ' ' ||
                   coalesce(array_to_string(NEW.aliases, ' '), ''));
    RETURN NEW;
END $$;


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: chinese; Type: TEXT SEARCH CONFIGURATION; Schema: public; Owner: -
--

CREATE TEXT SEARCH CONFIGURATION public.chinese (
    PARSER = public.zhparser );

ALTER TEXT SEARCH CONFIGURATION public.chinese
    ADD MAPPING FOR a WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.chinese
    ADD MAPPING FOR e WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.chinese
    ADD MAPPING FOR i WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.chinese
    ADD MAPPING FOR l WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.chinese
    ADD MAPPING FOR n WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.chinese
    ADD MAPPING FOR v WITH simple;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_run_projection; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_run_projection (
    run_id text NOT NULL,
    session_id text,
    query text NOT NULL,
    query_type text,
    channel text NOT NULL,
    status text NOT NULL,
    outcome_family text NOT NULL,
    outcome_code text NOT NULL,
    quality text NOT NULL,
    learning_eligible boolean DEFAULT false NOT NULL,
    early_exit boolean DEFAULT false NOT NULL,
    refused boolean DEFAULT false NOT NULL,
    iterations integer DEFAULT 0 NOT NULL,
    chunks_count integer DEFAULT 0 NOT NULL,
    tools_used jsonb DEFAULT '[]'::jsonb NOT NULL,
    evaluation jsonb DEFAULT '{}'::jsonb NOT NULL,
    runtime jsonb DEFAULT '{}'::jsonb NOT NULL,
    answer_preview text,
    request_id text,
    trace_id text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone DEFAULT now() NOT NULL,
    latency_ms integer DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: canonical_concepts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.canonical_concepts (
    id integer NOT NULL,
    concept_type character varying(50) NOT NULL,
    concept_name text NOT NULL,
    normalized_name text NOT NULL,
    aliases text[] DEFAULT '{}'::text[],
    preferred_route character varying(50) DEFAULT 'hybrid_search'::character varying,
    metadata jsonb DEFAULT '{}'::jsonb,
    embedding public.vector(1024),
    created_at timestamp without time zone DEFAULT now(),
    tsv tsvector
);


--
-- Name: canonical_concepts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.canonical_concepts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: canonical_concepts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.canonical_concepts_id_seq OWNED BY public.canonical_concepts.id;


--
-- Name: chunk_vector_views; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chunk_vector_views (
    id integer NOT NULL,
    chunk_id integer NOT NULL,
    view_type character varying(40) NOT NULL,
    view_text text NOT NULL,
    embedding public.vector(1024),
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: chunk_vector_views_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.chunk_vector_views_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: chunk_vector_views_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.chunk_vector_views_id_seq OWNED BY public.chunk_vector_views.id;


--
-- Name: concept_evidence_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.concept_evidence_links (
    id integer NOT NULL,
    concept_id integer NOT NULL,
    evidence_kind character varying(40) NOT NULL,
    source_table character varying(40) NOT NULL,
    source_id bigint DEFAULT 0 NOT NULL,
    doc_id text DEFAULT ''::text NOT NULL,
    file_name text DEFAULT ''::text NOT NULL,
    page_number integer DEFAULT 0 NOT NULL,
    parent_doc_id text DEFAULT ''::text NOT NULL,
    parent_page_number integer DEFAULT 0 NOT NULL,
    chunk_id integer DEFAULT 0 NOT NULL,
    link_score numeric(8,4) DEFAULT 1.0,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: concept_evidence_links_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.concept_evidence_links_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: concept_evidence_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.concept_evidence_links_id_seq OWNED BY public.concept_evidence_links.id;


--
-- Name: concept_relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.concept_relations (
    id integer NOT NULL,
    source_concept_id integer NOT NULL,
    target_concept_id integer NOT NULL,
    relation_kind character varying(50) NOT NULL,
    relation_weight numeric(8,4) DEFAULT 1.0,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: concept_relations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.concept_relations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: concept_relations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.concept_relations_id_seq OWNED BY public.concept_relations.id;


--
-- Name: conversation_turns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_turns (
    id bigint NOT NULL,
    session_id text NOT NULL,
    turn_index integer NOT NULL,
    user_content text NOT NULL,
    assistant_content text,
    message_id text,
    source text DEFAULT 'agent'::text,
    status text DEFAULT 'completed'::text,
    latency_ms integer,
    ts double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    run_id text,
    channel text DEFAULT 'sync'::text NOT NULL,
    outcome_code text,
    quality text,
    early_exit boolean DEFAULT false NOT NULL,
    CONSTRAINT conversation_turns_status_check CHECK ((status = ANY (ARRAY['completed'::text, 'cancelled'::text, 'error'::text])))
);


--
-- Name: conversation_turns_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.conversation_turns_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: conversation_turns_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.conversation_turns_id_seq OWNED BY public.conversation_turns.id;


--
-- Name: document_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_registry (
    id integer NOT NULL,
    file_name character varying(500) NOT NULL,
    file_path character varying(1000),
    doc_type character varying(50) DEFAULT 'general'::character varying,
    doc_code character varying(64),
    period character varying(7),
    total_pages integer,
    status character varying(50) DEFAULT 'imported'::character varying,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: document_registry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.document_registry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: document_registry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.document_registry_id_seq OWNED BY public.document_registry.id;


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    id integer NOT NULL,
    file_name character varying(500) NOT NULL,
    file_path character varying(1000),
    doc_type character varying(50) DEFAULT 'general'::character varying,
    period character varying(7),
    total_pages integer,
    status character varying(50) DEFAULT 'imported'::character varying,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.documents_id_seq OWNED BY public.documents.id;


--
-- Name: embedding_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.embedding_tasks (
    id integer NOT NULL,
    uuid uuid DEFAULT public.uuid_generate_v4(),
    task_type character varying(50) NOT NULL,
    entity_type character varying(50),
    entity_id integer,
    model_name character varying(100) NOT NULL,
    model_version character varying(50),
    embedding_dimension integer,
    status character varying(50) DEFAULT 'pending'::character varying,
    progress integer DEFAULT 0,
    error_message text,
    embedding_id character varying(255),
    vector_data jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    CONSTRAINT chk_task_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'processing'::character varying, 'completed'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: embedding_tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.embedding_tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: embedding_tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.embedding_tasks_id_seq OWNED BY public.embedding_tasks.id;


--
-- Name: entity_relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entity_relations (
    id integer NOT NULL,
    uuid uuid DEFAULT public.uuid_generate_v4(),
    source_entity_id integer NOT NULL,
    target_entity_id integer NOT NULL,
    relation_type character varying(100) NOT NULL,
    relation_strength double precision DEFAULT 1.0,
    properties jsonb DEFAULT '{}'::jsonb,
    source_type character varying(50),
    source_document_id integer,
    confidence double precision,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT chk_relation_strength CHECK (((relation_strength >= (0)::double precision) AND (relation_strength <= (1)::double precision)))
);


--
-- Name: entity_relations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.entity_relations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: entity_relations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.entity_relations_id_seq OWNED BY public.entity_relations.id;


--
-- Name: event_ledger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_ledger (
    event_id bigint NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    event_type text NOT NULL,
    run_id text,
    session_id text,
    request_id text,
    trace_id text,
    channel text NOT NULL,
    actor_service text NOT NULL,
    actor_kind text NOT NULL,
    outcome_family text,
    outcome_code text,
    quality text,
    learning_eligible boolean DEFAULT false NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    idempotency_key text,
    schema_version text DEFAULT 'phase6.v1'::text NOT NULL,
    topology_version text DEFAULT 'phase6.v1'::text NOT NULL,
    policy_version text DEFAULT 'phase6.v1'::text NOT NULL,
    prompt_version text DEFAULT 'phase6.v1'::text NOT NULL
);


--
-- Name: event_ledger_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.event_ledger_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: event_ledger_event_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.event_ledger_event_id_seq OWNED BY public.event_ledger.event_id;


--
-- Name: fee_rates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fee_rates (
    id integer NOT NULL,
    doc_id text,
    doc_code character varying(64),
    document_id integer,
    standard_year character varying(4),
    fee_name text NOT NULL,
    fee_category character varying(50),
    base_formula text,
    rate_min numeric(8,4),
    rate_max numeric(8,4),
    rate_recommended numeric(8,4),
    calc_base text,
    applicable_scope text,
    page_number integer,
    source_text text,
    embedding public.vector(1024),
    confidence double precision DEFAULT 1.0,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: fee_rates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fee_rates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fee_rates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fee_rates_id_seq OWNED BY public.fee_rates.id;


--
-- Name: improvement_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.improvement_events (
    id bigint NOT NULL,
    source text NOT NULL,
    source_feedback_id bigint,
    affected_route text,
    query_text text,
    problem text NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    severity_score double precision DEFAULT 0 NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    ts timestamp with time zone DEFAULT now() NOT NULL,
    verified_at timestamp with time zone,
    verification_result jsonb,
    actor text DEFAULT 'system'::text NOT NULL,
    source_radar_id bigint,
    source_run_id text,
    patch_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    rationale text,
    applied_at timestamp with time zone,
    reverted_at timestamp with time zone,
    reversible_by text DEFAULT 'rollback_event'::text NOT NULL
);


--
-- Name: improvement_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.improvement_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: improvement_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.improvement_events_id_seq OWNED BY public.improvement_events.id;


--
-- Name: knowledge_entities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_entities (
    id integer NOT NULL,
    uuid uuid DEFAULT public.uuid_generate_v4(),
    entity_name character varying(255) NOT NULL,
    entity_type character varying(100) NOT NULL,
    entity_category character varying(100),
    description text,
    properties jsonb DEFAULT '{}'::jsonb,
    source_type character varying(50),
    source_document_id integer,
    confidence double precision,
    related_entities text[],
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: knowledge_entities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.knowledge_entities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: knowledge_entities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.knowledge_entities_id_seq OWNED BY public.knowledge_entities.id;


--
-- Name: knowledge_gap_evidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_gap_evidence (
    id bigint NOT NULL,
    gap_key text NOT NULL,
    evidence_type text NOT NULL,
    actor text NOT NULL,
    source_run_id text,
    consultation_run_id text,
    session_id text,
    endpoint text,
    query_text text,
    answer_preview text,
    chunks_count integer,
    refused boolean,
    generic_answer boolean,
    quality text,
    outcome_code text,
    confidence numeric,
    decision text,
    decision_reason text,
    raw_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: knowledge_gap_evidence_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.knowledge_gap_evidence_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: knowledge_gap_evidence_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.knowledge_gap_evidence_id_seq OWNED BY public.knowledge_gap_evidence.id;


--
-- Name: knowledge_gap_repair_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_gap_repair_tasks (
    id bigint NOT NULL,
    gap_key text NOT NULL,
    task_type text NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    actor text NOT NULL,
    reason text NOT NULL,
    latest_evidence_ids bigint[] DEFAULT '{}'::bigint[] NOT NULL,
    issue_number integer,
    issue_url text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    CONSTRAINT knowledge_gap_repair_tasks_status_check CHECK ((status = ANY (ARRAY['open'::text, 'in_progress'::text, 'blocked'::text, 'resolved'::text, 'cancelled'::text])))
);


--
-- Name: knowledge_gap_repair_tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.knowledge_gap_repair_tasks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: knowledge_gap_repair_tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.knowledge_gap_repair_tasks_id_seq OWNED BY public.knowledge_gap_repair_tasks.id;


--
-- Name: knowledge_gap_transitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_gap_transitions (
    id bigint NOT NULL,
    gap_key text NOT NULL,
    from_status text,
    to_status text NOT NULL,
    action text NOT NULL,
    actor text NOT NULL,
    reason text,
    evidence_id bigint,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: knowledge_gap_transitions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.knowledge_gap_transitions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: knowledge_gap_transitions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.knowledge_gap_transitions_id_seq OWNED BY public.knowledge_gap_transitions.id;


--
-- Name: knowledge_gaps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_gaps (
    id bigint NOT NULL,
    gap_key text NOT NULL,
    problem_id text,
    description text NOT NULL,
    source text NOT NULL,
    affected_route text,
    query_text text,
    status text DEFAULT 'open'::text NOT NULL,
    quality text,
    resolution_plan text,
    related_issue_url text,
    confidence real DEFAULT 0.0 NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    verified_at timestamp with time zone,
    observation_until timestamp with time zone,
    last_reopened_at timestamp with time zone,
    scope_type text DEFAULT 'project'::text NOT NULL,
    scope_id text DEFAULT 'project'::text NOT NULL,
    cluster_id text,
    cause_type text,
    priority integer DEFAULT 0 NOT NULL,
    owner text,
    linked_event_id bigint,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    reopen_count integer DEFAULT 0 NOT NULL,
    CONSTRAINT knowledge_gaps_scope_type_check CHECK ((scope_type = ANY (ARRAY['user'::text, 'agent'::text, 'project'::text, 'global'::text]))),
    CONSTRAINT knowledge_gaps_source_check CHECK ((source = ANY (ARRAY['run'::text, 'problem'::text, 'feedback'::text, 'failure'::text, 'repeat_question'::text, 'contract_violation'::text, 'topology'::text]))),
    CONSTRAINT knowledge_gaps_status_check CHECK ((status = ANY (ARRAY['open'::text, 'in_progress'::text, 'observing'::text, 'resolved'::text, 'blocked'::text])))
);


--
-- Name: knowledge_gaps_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.knowledge_gaps_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: knowledge_gaps_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.knowledge_gaps_id_seq OWNED BY public.knowledge_gaps.id;


--
-- Name: learning_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.learning_runs (
    id bigint NOT NULL,
    run_id text NOT NULL,
    run_type text NOT NULL,
    result jsonb,
    status text NOT NULL,
    ts timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT learning_runs_run_type_valid CHECK ((run_type = ANY (ARRAY['scheduled'::text, 'manual'::text, 'auto_threshold'::text, 'feedback_analysis'::text])))
);


--
-- Name: learning_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.learning_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: learning_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.learning_runs_id_seq OWNED BY public.learning_runs.id;


--
-- Name: price_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.price_records (
    id integer NOT NULL,
    doc_id text,
    file_name text,
    material_name character varying(200) NOT NULL,
    specification character varying(200),
    unit character varying(20),
    price_tax_included numeric(12,2),
    price_tax_excluded numeric(12,2),
    region character varying(50) DEFAULT '深圳'::character varying,
    year_month character varying(7) NOT NULL,
    page_number integer,
    category character varying(100),
    metadata jsonb,
    embedding public.vector(1024),
    confidence double precision DEFAULT 1.0,
    price_formula text,
    agency_code character varying(50),
    seq_no integer,
    source_doc character varying(500),
    created_at timestamp without time zone DEFAULT now(),
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('public.chinese'::regconfig, (((COALESCE(material_name, ''::character varying))::text || ' '::text) || (COALESCE(specification, ''::character varying))::text))) STORED
);


--
-- Name: price_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.price_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: price_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.price_records_id_seq OWNED BY public.price_records.id;


--
-- Name: query_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.query_history (
    id integer NOT NULL,
    uuid uuid DEFAULT public.uuid_generate_v4(),
    query_text text NOT NULL,
    query_type character varying(50) DEFAULT 'text'::character varying,
    query_embedding jsonb,
    top_k integer DEFAULT 10,
    filters jsonb DEFAULT '{}'::jsonb,
    rerank_enabled boolean DEFAULT false,
    results jsonb,
    result_count integer,
    execution_time_ms integer,
    vector_search_time_ms integer,
    rerank_time_ms integer,
    user_id character varying(255),
    session_id character varying(255),
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT chk_query_type CHECK (((query_type)::text = ANY ((ARRAY['text'::character varying, 'table'::character varying, 'hybrid'::character varying])::text[])))
);


--
-- Name: query_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.query_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: query_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.query_history_id_seq OWNED BY public.query_history.id;


--
-- Name: rag_feedback; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rag_feedback (
    id bigint NOT NULL,
    ts double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL,
    session_id text NOT NULL,
    message_id text NOT NULL,
    rating smallint NOT NULL,
    comment text,
    query text,
    answer_summary text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    overall_rating smallint,
    rating_relevance smallint,
    rating_accuracy smallint,
    rating_completeness smallint,
    praise text,
    criticism text,
    suggestion text,
    tags text[],
    CONSTRAINT rag_feedback_overall_rating_check CHECK (((overall_rating >= 1) AND (overall_rating <= 5))),
    CONSTRAINT rag_feedback_rating_accuracy_check CHECK (((rating_accuracy >= 1) AND (rating_accuracy <= 5))),
    CONSTRAINT rag_feedback_rating_check CHECK ((rating = ANY (ARRAY['-1'::integer, 1]))),
    CONSTRAINT rag_feedback_rating_completeness_check CHECK (((rating_completeness >= 1) AND (rating_completeness <= 5))),
    CONSTRAINT rag_feedback_rating_relevance_check CHECK (((rating_relevance >= 1) AND (rating_relevance <= 5)))
);


--
-- Name: rag_feedback_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rag_feedback_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rag_feedback_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rag_feedback_id_seq OWNED BY public.rag_feedback.id;


--
-- Name: runtime_config_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_config_audit (
    id integer NOT NULL,
    ts timestamp with time zone DEFAULT now(),
    config_key text NOT NULL,
    old_value text,
    new_value text,
    applied boolean DEFAULT false NOT NULL,
    reason text,
    actor text DEFAULT 'guide-agent'::text
);


--
-- Name: runtime_config_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.runtime_config_audit_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: runtime_config_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.runtime_config_audit_id_seq OWNED BY public.runtime_config_audit.id;


--
-- Name: runtime_config_overrides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_config_overrides (
    config_key text NOT NULL,
    config_value text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by text DEFAULT 'guide-agent'::text NOT NULL,
    reason text,
    audit_id integer
);


--
-- Name: signal_contract_violation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signal_contract_violation (
    id bigint NOT NULL,
    run_id text,
    session_id text,
    contract_name text NOT NULL,
    violation_code text NOT NULL,
    payload jsonb,
    ts timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: signal_contract_violation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.signal_contract_violation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: signal_contract_violation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.signal_contract_violation_id_seq OWNED BY public.signal_contract_violation.id;


--
-- Name: signal_repeat_question; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signal_repeat_question (
    id bigint NOT NULL,
    session_id text NOT NULL,
    original_turn integer NOT NULL,
    repeat_turn integer NOT NULL,
    similarity real NOT NULL,
    ts timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: signal_repeat_question_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.signal_repeat_question_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: signal_repeat_question_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.signal_repeat_question_id_seq OWNED BY public.signal_repeat_question.id;


--
-- Name: system_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_config (
    id integer NOT NULL,
    config_key character varying(255) NOT NULL,
    config_value text NOT NULL,
    config_type character varying(50) DEFAULT 'string'::character varying,
    description text,
    is_secret boolean DEFAULT false,
    is_readonly boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: system_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.system_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: system_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.system_config_id_seq OWNED BY public.system_config.id;


--
-- Name: tech_radar; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tech_radar (
    id bigint NOT NULL,
    source text NOT NULL,
    external_id text,
    title text NOT NULL,
    summary text,
    url text,
    published_at timestamp with time zone,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    score integer DEFAULT 0 NOT NULL,
    tags text[],
    status text DEFAULT 'new'::text NOT NULL,
    reviewer text,
    decision_note text,
    related_issue integer,
    CONSTRAINT tech_radar_status_check CHECK ((status = ANY (ARRAY['new'::text, 'reviewing'::text, 'adopted'::text, 'dismissed'::text])))
);


--
-- Name: tech_radar_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tech_radar_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tech_radar_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tech_radar_id_seq OWNED BY public.tech_radar.id;


--
-- Name: text_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.text_chunks (
    id integer NOT NULL,
    doc_id text NOT NULL,
    file_name text,
    chunk_index integer,
    content text NOT NULL,
    page_number integer,
    section text,
    chunk_type character varying(30) DEFAULT 'article'::character varying,
    doc_type character varying(50),
    metadata jsonb DEFAULT '{}'::jsonb,
    embedding public.vector(1024),
    confidence double precision DEFAULT 1.0,
    created_at timestamp without time zone DEFAULT now(),
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('public.chinese'::regconfig, content)) STORED
);


--
-- Name: text_chunks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.text_chunks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: text_chunks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.text_chunks_id_seq OWNED BY public.text_chunks.id;


--
-- Name: topology_edge_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.topology_edge_log (
    edge_id text NOT NULL,
    from_node text NOT NULL,
    to_node text NOT NULL,
    last_traversed_at timestamp with time zone DEFAULT now() NOT NULL,
    traversal_count bigint DEFAULT 0 NOT NULL
);


--
-- Name: trend_points; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trend_points (
    id integer NOT NULL,
    series_key text NOT NULL,
    material_name character varying(200) NOT NULL,
    normalized_material character varying(200) NOT NULL,
    year_month character varying(7) NOT NULL,
    unit character varying(20),
    value numeric(12,4) NOT NULL,
    source_doc_id text,
    source_file_name text,
    source_chart_page integer,
    source_table_page integer,
    source_price_record_id integer,
    source_method character varying(50) DEFAULT 'derived_from_price_records'::character varying,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: trend_points_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.trend_points_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: trend_points_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.trend_points_id_seq OWNED BY public.trend_points.id;


--
-- Name: trend_relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trend_relations (
    id integer NOT NULL,
    series_key text NOT NULL,
    from_point_id integer NOT NULL,
    to_point_id integer NOT NULL,
    from_year_month character varying(7) NOT NULL,
    to_year_month character varying(7) NOT NULL,
    unit character varying(20),
    delta_value numeric(12,4) NOT NULL,
    delta_percent numeric(12,4),
    trend_direction character varying(10) NOT NULL,
    months_apart integer DEFAULT 1 NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: trend_relations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.trend_relations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: trend_relations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.trend_relations_id_seq OWNED BY public.trend_relations.id;


--
-- Name: canonical_concepts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canonical_concepts ALTER COLUMN id SET DEFAULT nextval('public.canonical_concepts_id_seq'::regclass);


--
-- Name: chunk_vector_views id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chunk_vector_views ALTER COLUMN id SET DEFAULT nextval('public.chunk_vector_views_id_seq'::regclass);


--
-- Name: concept_evidence_links id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concept_evidence_links ALTER COLUMN id SET DEFAULT nextval('public.concept_evidence_links_id_seq'::regclass);


--
-- Name: concept_relations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concept_relations ALTER COLUMN id SET DEFAULT nextval('public.concept_relations_id_seq'::regclass);


--
-- Name: conversation_turns id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_turns ALTER COLUMN id SET DEFAULT nextval('public.conversation_turns_id_seq'::regclass);


--
-- Name: document_registry id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_registry ALTER COLUMN id SET DEFAULT nextval('public.document_registry_id_seq'::regclass);


--
-- Name: documents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents ALTER COLUMN id SET DEFAULT nextval('public.documents_id_seq'::regclass);


--
-- Name: embedding_tasks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embedding_tasks ALTER COLUMN id SET DEFAULT nextval('public.embedding_tasks_id_seq'::regclass);


--
-- Name: entity_relations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_relations ALTER COLUMN id SET DEFAULT nextval('public.entity_relations_id_seq'::regclass);


--
-- Name: event_ledger event_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_ledger ALTER COLUMN event_id SET DEFAULT nextval('public.event_ledger_event_id_seq'::regclass);


--
-- Name: fee_rates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fee_rates ALTER COLUMN id SET DEFAULT nextval('public.fee_rates_id_seq'::regclass);


--
-- Name: improvement_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.improvement_events ALTER COLUMN id SET DEFAULT nextval('public.improvement_events_id_seq'::regclass);


--
-- Name: knowledge_entities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_entities ALTER COLUMN id SET DEFAULT nextval('public.knowledge_entities_id_seq'::regclass);


--
-- Name: knowledge_gap_evidence id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gap_evidence ALTER COLUMN id SET DEFAULT nextval('public.knowledge_gap_evidence_id_seq'::regclass);


--
-- Name: knowledge_gap_repair_tasks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gap_repair_tasks ALTER COLUMN id SET DEFAULT nextval('public.knowledge_gap_repair_tasks_id_seq'::regclass);


--
-- Name: knowledge_gap_transitions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gap_transitions ALTER COLUMN id SET DEFAULT nextval('public.knowledge_gap_transitions_id_seq'::regclass);


--
-- Name: knowledge_gaps id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gaps ALTER COLUMN id SET DEFAULT nextval('public.knowledge_gaps_id_seq'::regclass);


--
-- Name: learning_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_runs ALTER COLUMN id SET DEFAULT nextval('public.learning_runs_id_seq'::regclass);


--
-- Name: price_records id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.price_records ALTER COLUMN id SET DEFAULT nextval('public.price_records_id_seq'::regclass);


--
-- Name: query_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_history ALTER COLUMN id SET DEFAULT nextval('public.query_history_id_seq'::regclass);


--
-- Name: rag_feedback id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_feedback ALTER COLUMN id SET DEFAULT nextval('public.rag_feedback_id_seq'::regclass);


--
-- Name: runtime_config_audit id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_config_audit ALTER COLUMN id SET DEFAULT nextval('public.runtime_config_audit_id_seq'::regclass);


--
-- Name: signal_contract_violation id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_contract_violation ALTER COLUMN id SET DEFAULT nextval('public.signal_contract_violation_id_seq'::regclass);


--
-- Name: signal_repeat_question id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_repeat_question ALTER COLUMN id SET DEFAULT nextval('public.signal_repeat_question_id_seq'::regclass);


--
-- Name: system_config id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_config ALTER COLUMN id SET DEFAULT nextval('public.system_config_id_seq'::regclass);


--
-- Name: tech_radar id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tech_radar ALTER COLUMN id SET DEFAULT nextval('public.tech_radar_id_seq'::regclass);


--
-- Name: text_chunks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.text_chunks ALTER COLUMN id SET DEFAULT nextval('public.text_chunks_id_seq'::regclass);


--
-- Name: trend_points id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trend_points ALTER COLUMN id SET DEFAULT nextval('public.trend_points_id_seq'::regclass);


--
-- Name: trend_relations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trend_relations ALTER COLUMN id SET DEFAULT nextval('public.trend_relations_id_seq'::regclass);


--
-- Name: agent_run_projection agent_run_projection_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_projection
    ADD CONSTRAINT agent_run_projection_pkey PRIMARY KEY (run_id);


--
-- Name: canonical_concepts canonical_concepts_concept_type_normalized_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canonical_concepts
    ADD CONSTRAINT canonical_concepts_concept_type_normalized_name_key UNIQUE (concept_type, normalized_name);


--
-- Name: canonical_concepts canonical_concepts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canonical_concepts
    ADD CONSTRAINT canonical_concepts_pkey PRIMARY KEY (id);


--
-- Name: chunk_vector_views chunk_vector_views_chunk_id_view_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chunk_vector_views
    ADD CONSTRAINT chunk_vector_views_chunk_id_view_type_key UNIQUE (chunk_id, view_type);


--
-- Name: chunk_vector_views chunk_vector_views_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chunk_vector_views
    ADD CONSTRAINT chunk_vector_views_pkey PRIMARY KEY (id);


--
-- Name: concept_evidence_links concept_evidence_links_concept_id_evidence_kind_source_tabl_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concept_evidence_links
    ADD CONSTRAINT concept_evidence_links_concept_id_evidence_kind_source_tabl_key UNIQUE (concept_id, evidence_kind, source_table, source_id, doc_id, page_number, chunk_id);


--
-- Name: concept_evidence_links concept_evidence_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concept_evidence_links
    ADD CONSTRAINT concept_evidence_links_pkey PRIMARY KEY (id);


--
-- Name: concept_relations concept_relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concept_relations
    ADD CONSTRAINT concept_relations_pkey PRIMARY KEY (id);


--
-- Name: concept_relations concept_relations_source_concept_id_target_concept_id_relat_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concept_relations
    ADD CONSTRAINT concept_relations_source_concept_id_target_concept_id_relat_key UNIQUE (source_concept_id, target_concept_id, relation_kind);


--
-- Name: conversation_turns conversation_turns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_turns
    ADD CONSTRAINT conversation_turns_pkey PRIMARY KEY (id);


--
-- Name: conversation_turns conversation_turns_session_id_turn_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_turns
    ADD CONSTRAINT conversation_turns_session_id_turn_index_key UNIQUE (session_id, turn_index);


--
-- Name: document_registry document_registry_doc_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_registry
    ADD CONSTRAINT document_registry_doc_code_key UNIQUE (doc_code);


--
-- Name: document_registry document_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_registry
    ADD CONSTRAINT document_registry_pkey PRIMARY KEY (id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: embedding_tasks embedding_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embedding_tasks
    ADD CONSTRAINT embedding_tasks_pkey PRIMARY KEY (id);


--
-- Name: embedding_tasks embedding_tasks_uuid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embedding_tasks
    ADD CONSTRAINT embedding_tasks_uuid_key UNIQUE (uuid);


--
-- Name: entity_relations entity_relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_relations
    ADD CONSTRAINT entity_relations_pkey PRIMARY KEY (id);


--
-- Name: entity_relations entity_relations_uuid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_relations
    ADD CONSTRAINT entity_relations_uuid_key UNIQUE (uuid);


--
-- Name: event_ledger event_ledger_idempotency_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_ledger
    ADD CONSTRAINT event_ledger_idempotency_unique UNIQUE (idempotency_key);


--
-- Name: event_ledger event_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_ledger
    ADD CONSTRAINT event_ledger_pkey PRIMARY KEY (event_id);


--
-- Name: fee_rates fee_rates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fee_rates
    ADD CONSTRAINT fee_rates_pkey PRIMARY KEY (id);


--
-- Name: improvement_events improvement_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.improvement_events
    ADD CONSTRAINT improvement_events_pkey PRIMARY KEY (id);


--
-- Name: knowledge_entities knowledge_entities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_entities
    ADD CONSTRAINT knowledge_entities_pkey PRIMARY KEY (id);


--
-- Name: knowledge_entities knowledge_entities_uuid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_entities
    ADD CONSTRAINT knowledge_entities_uuid_key UNIQUE (uuid);


--
-- Name: knowledge_gap_evidence knowledge_gap_evidence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gap_evidence
    ADD CONSTRAINT knowledge_gap_evidence_pkey PRIMARY KEY (id);


--
-- Name: knowledge_gap_repair_tasks knowledge_gap_repair_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gap_repair_tasks
    ADD CONSTRAINT knowledge_gap_repair_tasks_pkey PRIMARY KEY (id);


--
-- Name: knowledge_gap_transitions knowledge_gap_transitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gap_transitions
    ADD CONSTRAINT knowledge_gap_transitions_pkey PRIMARY KEY (id);


--
-- Name: knowledge_gaps knowledge_gaps_gap_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gaps
    ADD CONSTRAINT knowledge_gaps_gap_key_key UNIQUE (gap_key);


--
-- Name: knowledge_gaps knowledge_gaps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gaps
    ADD CONSTRAINT knowledge_gaps_pkey PRIMARY KEY (id);


--
-- Name: learning_runs learning_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_runs
    ADD CONSTRAINT learning_runs_pkey PRIMARY KEY (id);


--
-- Name: learning_runs learning_runs_run_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.learning_runs
    ADD CONSTRAINT learning_runs_run_id_key UNIQUE (run_id);


--
-- Name: price_records price_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.price_records
    ADD CONSTRAINT price_records_pkey PRIMARY KEY (id);


--
-- Name: query_history query_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_history
    ADD CONSTRAINT query_history_pkey PRIMARY KEY (id);


--
-- Name: query_history query_history_uuid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_history
    ADD CONSTRAINT query_history_uuid_key UNIQUE (uuid);


--
-- Name: rag_feedback rag_feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_feedback
    ADD CONSTRAINT rag_feedback_pkey PRIMARY KEY (id);


--
-- Name: rag_feedback rag_feedback_session_message_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_feedback
    ADD CONSTRAINT rag_feedback_session_message_unique UNIQUE (session_id, message_id);


--
-- Name: runtime_config_audit runtime_config_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_config_audit
    ADD CONSTRAINT runtime_config_audit_pkey PRIMARY KEY (id);


--
-- Name: runtime_config_overrides runtime_config_overrides_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_config_overrides
    ADD CONSTRAINT runtime_config_overrides_pkey PRIMARY KEY (config_key);


--
-- Name: signal_contract_violation signal_contract_violation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_contract_violation
    ADD CONSTRAINT signal_contract_violation_pkey PRIMARY KEY (id);


--
-- Name: signal_repeat_question signal_repeat_question_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_repeat_question
    ADD CONSTRAINT signal_repeat_question_pkey PRIMARY KEY (id);


--
-- Name: system_config system_config_config_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_config
    ADD CONSTRAINT system_config_config_key_key UNIQUE (config_key);


--
-- Name: system_config system_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_config
    ADD CONSTRAINT system_config_pkey PRIMARY KEY (id);


--
-- Name: tech_radar tech_radar_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tech_radar
    ADD CONSTRAINT tech_radar_pkey PRIMARY KEY (id);


--
-- Name: tech_radar tech_radar_source_extid_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tech_radar
    ADD CONSTRAINT tech_radar_source_extid_unique UNIQUE (source, external_id);


--
-- Name: text_chunks text_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.text_chunks
    ADD CONSTRAINT text_chunks_pkey PRIMARY KEY (id);


--
-- Name: topology_edge_log topology_edge_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topology_edge_log
    ADD CONSTRAINT topology_edge_log_pkey PRIMARY KEY (edge_id);


--
-- Name: trend_points trend_points_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trend_points
    ADD CONSTRAINT trend_points_pkey PRIMARY KEY (id);


--
-- Name: trend_points trend_points_series_key_year_month_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trend_points
    ADD CONSTRAINT trend_points_series_key_year_month_key UNIQUE (series_key, year_month);


--
-- Name: trend_relations trend_relations_from_point_id_to_point_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trend_relations
    ADD CONSTRAINT trend_relations_from_point_id_to_point_id_key UNIQUE (from_point_id, to_point_id);


--
-- Name: trend_relations trend_relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trend_relations
    ADD CONSTRAINT trend_relations_pkey PRIMARY KEY (id);


--
-- Name: knowledge_entities uk_entity_name_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_entities
    ADD CONSTRAINT uk_entity_name_type UNIQUE (entity_name, entity_type);


--
-- Name: entity_relations uq_source_target_relation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_relations
    ADD CONSTRAINT uq_source_target_relation UNIQUE (source_entity_id, target_entity_id, relation_type);


--
-- Name: idx_agent_run_projection_completed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_run_projection_completed ON public.agent_run_projection USING btree (completed_at DESC);


--
-- Name: idx_agent_run_projection_learning; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_run_projection_learning ON public.agent_run_projection USING btree (learning_eligible, completed_at DESC);


--
-- Name: idx_agent_run_projection_quality; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_run_projection_quality ON public.agent_run_projection USING btree (quality, completed_at DESC);


--
-- Name: idx_agent_run_projection_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_run_projection_session ON public.agent_run_projection USING btree (session_id, completed_at DESC);


--
-- Name: idx_canonical_concepts_tsv_chinese; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_canonical_concepts_tsv_chinese ON public.canonical_concepts USING gin (tsv);


--
-- Name: idx_cc_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cc_embedding ON public.canonical_concepts USING hnsw (embedding public.vector_cosine_ops) WHERE (embedding IS NOT NULL);


--
-- Name: idx_cc_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cc_name_trgm ON public.canonical_concepts USING gin (concept_name public.gin_trgm_ops);


--
-- Name: idx_cc_type_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cc_type_name ON public.canonical_concepts USING btree (concept_type, concept_name);


--
-- Name: idx_cel_concept; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cel_concept ON public.concept_evidence_links USING btree (concept_id, evidence_kind);


--
-- Name: idx_cel_doc_page; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cel_doc_page ON public.concept_evidence_links USING btree (doc_id, page_number);


--
-- Name: idx_cel_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cel_source ON public.concept_evidence_links USING btree (source_table, source_id);


--
-- Name: idx_conv_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conv_channel ON public.conversation_turns USING btree (channel, ts DESC);


--
-- Name: idx_conv_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conv_run_id ON public.conversation_turns USING btree (run_id);


--
-- Name: idx_conv_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conv_session ON public.conversation_turns USING btree (session_id, turn_index DESC);


--
-- Name: idx_conv_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conv_ts ON public.conversation_turns USING btree (ts DESC);


--
-- Name: idx_cr_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cr_source ON public.concept_relations USING btree (source_concept_id);


--
-- Name: idx_cr_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cr_target ON public.concept_relations USING btree (target_concept_id);


--
-- Name: idx_cvv_chunk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cvv_chunk ON public.chunk_vector_views USING btree (chunk_id, view_type);


--
-- Name: idx_cvv_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cvv_embedding ON public.chunk_vector_views USING hnsw (embedding public.vector_cosine_ops) WHERE (embedding IS NOT NULL);


--
-- Name: idx_cvv_view_text_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cvv_view_text_trgm ON public.chunk_vector_views USING gin (view_text public.gin_trgm_ops);


--
-- Name: idx_documents_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_created ON public.documents USING btree (created_at);


--
-- Name: idx_documents_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_status ON public.documents USING btree (status);


--
-- Name: idx_documents_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_type ON public.documents USING btree (doc_type);


--
-- Name: idx_embedding_tasks_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_embedding_tasks_entity ON public.embedding_tasks USING btree (entity_id, entity_type);


--
-- Name: idx_embedding_tasks_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_embedding_tasks_status ON public.embedding_tasks USING btree (status);


--
-- Name: idx_entities_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entities_category ON public.knowledge_entities USING btree (entity_category);


--
-- Name: idx_entities_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entities_source ON public.knowledge_entities USING btree (source_document_id);


--
-- Name: idx_entities_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entities_type ON public.knowledge_entities USING btree (entity_type);


--
-- Name: idx_event_ledger_aggregate; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_ledger_aggregate ON public.event_ledger USING btree (aggregate_type, aggregate_id, occurred_at DESC);


--
-- Name: idx_event_ledger_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_ledger_event_type ON public.event_ledger USING btree (event_type, occurred_at DESC);


--
-- Name: idx_event_ledger_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_ledger_run_id ON public.event_ledger USING btree (run_id, occurred_at DESC);


--
-- Name: idx_event_ledger_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_ledger_session_id ON public.event_ledger USING btree (session_id, occurred_at DESC);


--
-- Name: idx_fr_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fr_category ON public.fee_rates USING btree (fee_category);


--
-- Name: idx_fr_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fr_embedding ON public.fee_rates USING hnsw (embedding public.vector_cosine_ops) WHERE (embedding IS NOT NULL);


--
-- Name: idx_fr_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fr_name_trgm ON public.fee_rates USING gin (fee_name public.gin_trgm_ops);


--
-- Name: idx_fr_year; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fr_year ON public.fee_rates USING btree (standard_year);


--
-- Name: idx_gap_evidence_consultation_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gap_evidence_consultation_run ON public.knowledge_gap_evidence USING btree (consultation_run_id);


--
-- Name: idx_gap_evidence_gap_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gap_evidence_gap_created ON public.knowledge_gap_evidence USING btree (gap_key, created_at DESC);


--
-- Name: idx_gap_evidence_type_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gap_evidence_type_created ON public.knowledge_gap_evidence USING btree (evidence_type, created_at DESC);


--
-- Name: idx_gap_repair_tasks_gap_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gap_repair_tasks_gap_status ON public.knowledge_gap_repair_tasks USING btree (gap_key, status);


--
-- Name: idx_gap_repair_tasks_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gap_repair_tasks_status_created ON public.knowledge_gap_repair_tasks USING btree (status, created_at DESC);


--
-- Name: idx_gap_transitions_gap_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gap_transitions_gap_time ON public.knowledge_gap_transitions USING btree (gap_key, occurred_at DESC);


--
-- Name: idx_gap_transitions_status_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gap_transitions_status_time ON public.knowledge_gap_transitions USING btree (to_status, occurred_at DESC);


--
-- Name: idx_improve_applied; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_improve_applied ON public.improvement_events USING btree (applied_at DESC);


--
-- Name: idx_improve_feedback; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_improve_feedback ON public.improvement_events USING btree (source_feedback_id);


--
-- Name: idx_improve_route; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_improve_route ON public.improvement_events USING btree (affected_route);


--
-- Name: idx_improve_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_improve_source ON public.improvement_events USING btree (source);


--
-- Name: idx_improve_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_improve_ts ON public.improvement_events USING btree (ts DESC);


--
-- Name: idx_improve_verified; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_improve_verified ON public.improvement_events USING btree (verified_at DESC);


--
-- Name: idx_knowledge_gaps_cluster; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_gaps_cluster ON public.knowledge_gaps USING btree (cluster_id);


--
-- Name: idx_knowledge_gaps_observation_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_gaps_observation_until ON public.knowledge_gaps USING btree (observation_until) WHERE (status = 'observing'::text);


--
-- Name: idx_knowledge_gaps_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_gaps_priority ON public.knowledge_gaps USING btree (priority DESC, last_seen_at DESC);


--
-- Name: idx_knowledge_gaps_problem_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_gaps_problem_id ON public.knowledge_gaps USING btree (problem_id);


--
-- Name: idx_knowledge_gaps_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_gaps_scope ON public.knowledge_gaps USING btree (scope_type, scope_id);


--
-- Name: idx_knowledge_gaps_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_gaps_status ON public.knowledge_gaps USING btree (status);


--
-- Name: idx_knowledge_gaps_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_gaps_updated_at ON public.knowledge_gaps USING btree (updated_at DESC);


--
-- Name: idx_learning_runs_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_learning_runs_run_id ON public.learning_runs USING btree (run_id);


--
-- Name: idx_learning_runs_run_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_learning_runs_run_type ON public.learning_runs USING btree (run_type);


--
-- Name: idx_learning_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_learning_runs_status ON public.learning_runs USING btree (status);


--
-- Name: idx_learning_runs_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_learning_runs_ts ON public.learning_runs USING btree (ts DESC);


--
-- Name: idx_pr_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_category ON public.price_records USING btree (category);


--
-- Name: idx_pr_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_embedding ON public.price_records USING hnsw (embedding public.vector_cosine_ops) WHERE (embedding IS NOT NULL);


--
-- Name: idx_pr_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_name_trgm ON public.price_records USING gin (material_name public.gin_trgm_ops);


--
-- Name: idx_pr_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_period ON public.price_records USING btree (year_month);


--
-- Name: idx_pr_spec_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_spec_trgm ON public.price_records USING gin (specification public.gin_trgm_ops);


--
-- Name: idx_price_records_tsv_chinese; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_price_records_tsv_chinese ON public.price_records USING gin (tsv);


--
-- Name: idx_queries_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_queries_created ON public.query_history USING btree (created_at);


--
-- Name: idx_queries_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_queries_session ON public.query_history USING btree (session_id);


--
-- Name: idx_queries_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_queries_user ON public.query_history USING btree (user_id);


--
-- Name: idx_rag_feedback_rating; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rag_feedback_rating ON public.rag_feedback USING btree (rating);


--
-- Name: idx_rag_feedback_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rag_feedback_session ON public.rag_feedback USING btree (session_id);


--
-- Name: idx_rag_feedback_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rag_feedback_ts ON public.rag_feedback USING btree (ts DESC);


--
-- Name: idx_relations_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_relations_source ON public.entity_relations USING btree (source_entity_id);


--
-- Name: idx_relations_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_relations_target ON public.entity_relations USING btree (target_entity_id);


--
-- Name: idx_relations_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_relations_type ON public.entity_relations USING btree (relation_type);


--
-- Name: idx_repeat_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_repeat_ts ON public.signal_repeat_question USING btree (ts DESC);


--
-- Name: idx_tc_content; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tc_content ON public.text_chunks USING gin (content public.gin_trgm_ops);


--
-- Name: idx_tc_doc_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tc_doc_id ON public.text_chunks USING btree (doc_id);


--
-- Name: idx_tc_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tc_embedding ON public.text_chunks USING hnsw (embedding public.vector_cosine_ops) WHERE (embedding IS NOT NULL);


--
-- Name: idx_tc_file; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tc_file ON public.text_chunks USING btree (file_name);


--
-- Name: idx_tech_radar_fetched; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tech_radar_fetched ON public.tech_radar USING btree (fetched_at DESC);


--
-- Name: idx_tech_radar_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tech_radar_source ON public.tech_radar USING btree (source);


--
-- Name: idx_tech_radar_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tech_radar_status ON public.tech_radar USING btree (status);


--
-- Name: idx_text_chunks_tsv_chinese; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_text_chunks_tsv_chinese ON public.text_chunks USING gin (tsv);


--
-- Name: idx_tp_doc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tp_doc ON public.trend_points USING btree (source_doc_id);


--
-- Name: idx_tp_material; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tp_material ON public.trend_points USING btree (normalized_material, year_month);


--
-- Name: idx_tp_series; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tp_series ON public.trend_points USING btree (series_key, year_month);


--
-- Name: idx_tr_from_point; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tr_from_point ON public.trend_relations USING btree (from_point_id);


--
-- Name: idx_tr_series; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tr_series ON public.trend_relations USING btree (series_key, from_year_month, to_year_month);


--
-- Name: idx_tr_to_point; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tr_to_point ON public.trend_relations USING btree (to_point_id);


--
-- Name: idx_violation_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_violation_code ON public.signal_contract_violation USING btree (violation_code);


--
-- Name: idx_violation_contract; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_violation_contract ON public.signal_contract_violation USING btree (contract_name);


--
-- Name: idx_violation_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_violation_ts ON public.signal_contract_violation USING btree (ts DESC);


--
-- Name: uq_gap_repair_tasks_active_gap_type; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_gap_repair_tasks_active_gap_type ON public.knowledge_gap_repair_tasks USING btree (gap_key, task_type) WHERE (status = ANY (ARRAY['open'::text, 'in_progress'::text]));


--
-- Name: canonical_concepts trig_canonical_concepts_tsv; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trig_canonical_concepts_tsv BEFORE INSERT OR UPDATE OF concept_name, aliases ON public.canonical_concepts FOR EACH ROW EXECUTE FUNCTION public.canonical_concepts_tsv_trigger();


--
-- Name: embedding_tasks update_embedding_tasks_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_embedding_tasks_updated_at BEFORE UPDATE ON public.embedding_tasks FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: knowledge_entities update_entities_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_entities_updated_at BEFORE UPDATE ON public.knowledge_entities FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: entity_relations update_entity_relations_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_entity_relations_updated_at BEFORE UPDATE ON public.entity_relations FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: system_config update_system_config_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_system_config_updated_at BEFORE UPDATE ON public.system_config FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: chunk_vector_views chunk_vector_views_chunk_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chunk_vector_views
    ADD CONSTRAINT chunk_vector_views_chunk_id_fkey FOREIGN KEY (chunk_id) REFERENCES public.text_chunks(id) ON DELETE CASCADE;


--
-- Name: concept_evidence_links concept_evidence_links_concept_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concept_evidence_links
    ADD CONSTRAINT concept_evidence_links_concept_id_fkey FOREIGN KEY (concept_id) REFERENCES public.canonical_concepts(id) ON DELETE CASCADE;


--
-- Name: concept_relations concept_relations_source_concept_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concept_relations
    ADD CONSTRAINT concept_relations_source_concept_id_fkey FOREIGN KEY (source_concept_id) REFERENCES public.canonical_concepts(id) ON DELETE CASCADE;


--
-- Name: concept_relations concept_relations_target_concept_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.concept_relations
    ADD CONSTRAINT concept_relations_target_concept_id_fkey FOREIGN KEY (target_concept_id) REFERENCES public.canonical_concepts(id) ON DELETE CASCADE;


--
-- Name: entity_relations entity_relations_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_relations
    ADD CONSTRAINT entity_relations_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.documents(id) ON DELETE SET NULL;


--
-- Name: entity_relations entity_relations_source_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_relations
    ADD CONSTRAINT entity_relations_source_entity_id_fkey FOREIGN KEY (source_entity_id) REFERENCES public.knowledge_entities(id) ON DELETE CASCADE;


--
-- Name: entity_relations entity_relations_target_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_relations
    ADD CONSTRAINT entity_relations_target_entity_id_fkey FOREIGN KEY (target_entity_id) REFERENCES public.knowledge_entities(id) ON DELETE CASCADE;


--
-- Name: knowledge_entities knowledge_entities_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_entities
    ADD CONSTRAINT knowledge_entities_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.documents(id) ON DELETE SET NULL;


--
-- Name: knowledge_gap_evidence knowledge_gap_evidence_gap_key_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gap_evidence
    ADD CONSTRAINT knowledge_gap_evidence_gap_key_fkey FOREIGN KEY (gap_key) REFERENCES public.knowledge_gaps(gap_key) ON DELETE CASCADE;


--
-- Name: knowledge_gap_repair_tasks knowledge_gap_repair_tasks_gap_key_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gap_repair_tasks
    ADD CONSTRAINT knowledge_gap_repair_tasks_gap_key_fkey FOREIGN KEY (gap_key) REFERENCES public.knowledge_gaps(gap_key) ON DELETE CASCADE;


--
-- Name: knowledge_gap_transitions knowledge_gap_transitions_evidence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gap_transitions
    ADD CONSTRAINT knowledge_gap_transitions_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES public.knowledge_gap_evidence(id) ON DELETE SET NULL;


--
-- Name: knowledge_gap_transitions knowledge_gap_transitions_gap_key_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gap_transitions
    ADD CONSTRAINT knowledge_gap_transitions_gap_key_fkey FOREIGN KEY (gap_key) REFERENCES public.knowledge_gaps(gap_key) ON DELETE CASCADE;


--
-- Name: knowledge_gaps knowledge_gaps_linked_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_gaps
    ADD CONSTRAINT knowledge_gaps_linked_event_id_fkey FOREIGN KEY (linked_event_id) REFERENCES public.improvement_events(id) ON DELETE SET NULL;


--
-- Name: runtime_config_overrides runtime_config_overrides_audit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_config_overrides
    ADD CONSTRAINT runtime_config_overrides_audit_id_fkey FOREIGN KEY (audit_id) REFERENCES public.runtime_config_audit(id);


--
-- Name: trend_relations trend_relations_from_point_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trend_relations
    ADD CONSTRAINT trend_relations_from_point_id_fkey FOREIGN KEY (from_point_id) REFERENCES public.trend_points(id) ON DELETE CASCADE;


--
-- Name: trend_relations trend_relations_to_point_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trend_relations
    ADD CONSTRAINT trend_relations_to_point_id_fkey FOREIGN KEY (to_point_id) REFERENCES public.trend_points(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


