"""AgentForge Arena v0.1 runner — task loading, agents, sandboxing, clean-room
grading, run orchestration, persistence, and reporting. Builds on afa_kernel.
Pure stdlib, offline.
"""

from __future__ import annotations

from .task import DomainTag, Task, TestSuiteSpec, load_task
from .agents import Agent, AgentOutcome, MockAgent, ScriptAgent, SequenceAgent
from .agents_ollama import OllamaAgent, ollama_generate
from .agents_openai import OpenAICompatAgent, openai_chat_generate
from .sandbox import CommandResult, LocalSandbox, Sandbox
from .diffing import Diff, apply_diff, capture_diff, snapshot_tree
from .grader import GradeReport, SuiteOutcome, grade
from .pipeline import RunRecord, aggregate_group, run_group, run_once, validate_task
from .store import RunStore, SqliteRunStore
from .report import domain_profile, format_leaderboard, leaderboard, task_aggregate
from .report_html import render_report

__all__ = [
    "Task", "TestSuiteSpec", "DomainTag", "load_task",
    "Agent", "AgentOutcome", "MockAgent", "ScriptAgent", "SequenceAgent",
    "OllamaAgent", "ollama_generate",
    "OpenAICompatAgent", "openai_chat_generate",
    "Sandbox", "LocalSandbox", "CommandResult",
    "Diff", "snapshot_tree", "capture_diff", "apply_diff",
    "GradeReport", "SuiteOutcome", "grade",
    "RunRecord", "run_once", "run_group", "aggregate_group", "validate_task",
    "RunStore", "SqliteRunStore",
    "leaderboard", "domain_profile", "task_aggregate", "format_leaderboard",
    "render_report",
]

__version__ = "0.1.0"
