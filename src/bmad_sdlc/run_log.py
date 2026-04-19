"""
run_log.py — Structured YAML run log for audit trail.

Each automation run produces a run_log.yaml — the primary artifact
Carlos reviews to understand what the automation did and why.
Saved after every step completion for crash-safe auditability.

Phase 2: Added status enum, schema validation, dual duration metrics,
pause/resume timestamps, intervention classification, replace-on-resume.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

import yaml


class StepStatus(str, Enum):
    """Canonical step status values (Phase 2 spec 4.2.1)."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    COMPLETED_WITH_GAPS = "completed-with-gaps"
    SKIPPED = "skipped"

    def __str__(self):
        return self.value


@dataclass
class InterventionDetail:
    """A single human intervention record."""
    type: str = ""          # "planned" (Mode B) or "unplanned" (bug/crash)
    reason: str = ""
    step: str = ""


@dataclass
class HumanInterventions:
    """Classified human intervention tracking (Phase 2 spec 4.2.5)."""
    planned: int = 0
    unplanned: int = 0
    details: list[InterventionDetail] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.planned + self.unplanned

    def add_planned(self, reason: str, step: str):
        self.planned += 1
        self.details.append(InterventionDetail(
            type="planned", reason=reason, step=step
        ))

    def add_unplanned(self, reason: str, step: str):
        self.unplanned += 1
        self.details.append(InterventionDetail(
            type="unplanned", reason=reason, step=step
        ))


@dataclass
class StepLog:
    step: str
    mode: dict                                      # from STEP_MODES: {mode, type}
    status: str = StepStatus.PENDING                # Uses StepStatus values
    started: str = ""
    duration_seconds: int = 0
    attempt: int = 1                                # Phase 2: attempt counter for retries
    paused_at: str = ""                             # Phase 2: timestamp when paused
    resumed_at: str = ""                            # Phase 2: timestamp when resumed
    pause_duration_seconds: int = 0                 # Phase 2: elapsed time during pause
    artifacts_produced: list = field(default_factory=list)
    findings: dict = field(default_factory=dict)
    fixes_applied: list = field(default_factory=list)
    escalation: dict = field(default_factory=dict)
    state_after: str = ""


@dataclass
class RunLog:
    story: str
    story_type: str = "feature"
    started: str = ""
    status: str = "running"                         # running | completed | stopped | paused | failed
    dev_model: str = ""
    review_model: str = ""
    review_mode: str = "A"
    steps: list[StepLog] = field(default_factory=list)
    completed: str = ""
    execution_time_seconds: int = 0                 # Phase 2: sum of step durations
    wall_clock_seconds: int = 0                     # Phase 2: started to completed
    total_duration_seconds: int = 0                 # Legacy: kept for backward compat
    human_interventions: HumanInterventions = field(default_factory=HumanInterventions)
    stopped_after: str = ""                           # Step name when --stop-after was used
    prompt_sizes: dict = field(default_factory=dict)  # step → char count
    recovered: bool = False                         # Phase 2: True if reconstructed from partial state

    def compute_execution_time(self) -> int:
        """Sum of all step duration_seconds (actual execution, excludes pauses)."""
        return sum(s.duration_seconds for s in self.steps if s.duration_seconds > 0)

    def compute_wall_clock(self) -> int:
        """Wall clock from started to completed."""
        if not self.started or not self.completed:
            return 0
        try:
            start = datetime.fromisoformat(self.started)
            end = datetime.fromisoformat(self.completed)
            return int((end - start).total_seconds())
        except (ValueError, TypeError):
            return 0

    def find_step(self, step_name: str, attempt: int | None = None) -> StepLog | None:
        """Find a step entry by name and optionally by attempt number."""
        for s in reversed(self.steps):
            if s.step == step_name:
                if attempt is None or s.attempt == attempt:
                    return s
        return None

    def replace_or_append_step(self, step_log: StepLog):
        """Replace existing step entry on resume, or append if new (Phase 2 spec 4.2.2).

        Matches by step name + attempt. If found, replaces in-place.
        If not found, appends.
        """
        for i, existing in enumerate(self.steps):
            if existing.step == step_log.step and existing.attempt == step_log.attempt:
                self.steps[i] = step_log
                return
        self.steps.append(step_log)

    def next_attempt(self, step_name: str) -> int:
        """Get the next attempt number for a step."""
        max_attempt = 0
        for s in self.steps:
            if s.step == step_name:
                max_attempt = max(max_attempt, s.attempt)
        return max_attempt + 1

    def validate_schema(self) -> list[str]:
        """Validate run log structure. Returns list of errors (empty = valid).

        Phase 2 spec 4.2.6: validate on every write.
        """
        errors = []

        if not self.story:
            errors.append("Missing required field: story")

        if not self.started:
            errors.append("Missing required field: started")
        elif not _is_valid_iso(self.started):
            errors.append(f"Invalid ISO timestamp in 'started': {self.started}")

        if self.completed and not _is_valid_iso(self.completed):
            errors.append(f"Invalid ISO timestamp in 'completed': {self.completed}")

        valid_statuses = {s.value for s in StepStatus}
        for step in self.steps:
            if step.status not in valid_statuses:
                errors.append(f"Step '{step.step}' has invalid status: {step.status}")
            if step.started and not _is_valid_iso(step.started):
                errors.append(f"Step '{step.step}' has invalid ISO timestamp: {step.started}")
            if step.paused_at and not _is_valid_iso(step.paused_at):
                errors.append(f"Step '{step.step}' has invalid paused_at timestamp: {step.paused_at}")
            if step.resumed_at and not _is_valid_iso(step.resumed_at):
                errors.append(f"Step '{step.step}' has invalid resumed_at timestamp: {step.resumed_at}")
            if step.attempt < 1:
                errors.append(f"Step '{step.step}' has invalid attempt: {step.attempt}")

        return errors

    def save(self, path: Path):
        """Save after every step completion — crash-safe audit trail.

        Validates schema before writing (Phase 2 spec 4.2.6).
        """
        errors = self.validate_schema()
        if errors:
            import logging
            log = logging.getLogger("bmad_sdlc.run_log")
            log.warning(f"Run log schema warnings: {errors}")

        # Update computed metrics
        self.execution_time_seconds = self.compute_execution_time()
        if self.completed:
            self.wall_clock_seconds = self.compute_wall_clock()

        # Keep legacy field in sync
        self.total_duration_seconds = self.execution_time_seconds

        data = asdict(self)

        # Ensure StepStatus enum values are plain strings for yaml.safe_load compat
        for step in data.get("steps", []):
            if isinstance(step.get("status"), StepStatus):
                step["status"] = str(step["status"])

        # Convert HumanInterventions to clean dict for YAML
        if isinstance(data.get("human_interventions"), dict):
            hi = data["human_interventions"]
            # Remove empty details list for cleaner YAML
            if not hi.get("details"):
                hi.pop("details", None)

        # Strip empty optional fields from steps for cleaner YAML
        for step in data.get("steps", []):
            for key in ["paused_at", "resumed_at", "pause_duration_seconds"]:
                if not step.get(key):
                    step.pop(key, None)

        # Use a custom representer to ensure StepStatus enums serialize as plain strings
        dumper = yaml.Dumper
        dumper.add_representer(StepStatus, lambda d, s: d.represent_str(str(s)))

        with open(path, "w") as f:
            yaml.dump(data, f, Dumper=dumper, default_flow_style=False, sort_keys=False)

    @classmethod
    def load(cls, path: Path) -> "RunLog":
        """Load from YAML for --resume.

        Handles legacy formats (Phase 1 run logs) gracefully.
        """
        with open(path) as f:
            data = yaml.safe_load(f)

        log = cls(story=data["story"])
        for k, v in data.items():
            if k == "steps":
                log.steps = [_load_step(s) for s in v]
            elif k == "human_interventions":
                log.human_interventions = _load_interventions(v)
            elif hasattr(log, k):
                setattr(log, k, v)

        # Normalize legacy hyphenated timestamps to proper ISO
        log.started = _normalize_timestamp(log.started)
        if log.completed:
            log.completed = _normalize_timestamp(log.completed)
        for step in log.steps:
            step.started = _normalize_timestamp(step.started)
            if step.paused_at:
                step.paused_at = _normalize_timestamp(step.paused_at)
            if step.resumed_at:
                step.resumed_at = _normalize_timestamp(step.resumed_at)

        return log


def _load_step(data: dict) -> StepLog:
    """Load a StepLog from dict, handling missing Phase 2 fields."""
    known_fields = {f.name for f in StepLog.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in known_fields}
    # Default attempt to 1 for legacy logs
    if "attempt" not in filtered:
        filtered["attempt"] = 1
    return StepLog(**filtered)


def _load_interventions(data) -> HumanInterventions:
    """Load HumanInterventions from dict or legacy int format."""
    if isinstance(data, int):
        # Legacy format: just an int count — treat all as unclassified planned
        return HumanInterventions(planned=data, unplanned=0)
    if isinstance(data, dict):
        details = []
        for d in data.get("details", []):
            if isinstance(d, dict):
                details.append(InterventionDetail(**d))
        return HumanInterventions(
            planned=data.get("planned", 0),
            unplanned=data.get("unplanned", 0),
            details=details,
        )
    return HumanInterventions()


def _normalize_timestamp(ts: str) -> str:
    """Normalize legacy hyphenated timestamps to proper ISO 8601."""
    if not ts or "T" not in ts:
        return ts
    date_part, time_part = ts.split("T", 1)
    if "-" in time_part and ":" not in time_part:
        return f"{date_part}T{time_part.replace('-', ':', 2)}"
    return ts


def _is_valid_iso(ts: str) -> bool:
    """Check if a string is a valid ISO 8601 timestamp."""
    if not ts:
        return False
    try:
        datetime.fromisoformat(ts)
        return True
    except (ValueError, TypeError):
        return False
