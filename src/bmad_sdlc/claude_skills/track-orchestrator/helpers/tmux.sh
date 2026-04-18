#!/bin/bash
# BMPIPE Track Orchestrator — tmux session management
#
# Usage:
#   tmux.sh spawn <track-id> <story-key> <command>   # Create a detached tmux session
#   tmux.sh status <track-id>                         # Check if session exists (0=yes, 1=no)
#   tmux.sh attach-cmd <track-id>                     # Print attach command
#   tmux.sh kill <track-id>                           # Kill the session
#   tmux.sh list                                      # List all track sessions
#   tmux.sh check-exit <track-id>                     # Read exit code from sentinel
#   tmux.sh check-done <track-id>                     # Check if session completed
#   tmux.sh cleanup <track-id>                        # Remove sentinel files

SESSION_PREFIX="${BMPIPE_SESSION_PREFIX:-bmpipe-track}"
PROJECT_ROOT="${BMPIPE_PROJECT_ROOT:-$(pwd)}"
ORCH_STATE="$PROJECT_ROOT/.orchestrator"

session_name() {
  echo "${SESSION_PREFIX}-$1"
}

cmd_spawn() {
  local track_id="$1"
  local story_key="$2"
  local command="$3"
  local session
  session=$(session_name "$track_id")

  if tmux has-session -t "$session" 2>/dev/null; then
    echo "ERROR: Session $session already exists" >&2
    return 1
  fi

  mkdir -p "$ORCH_STATE/sentinels" "$ORCH_STATE/logs"
  local log_file="$ORCH_STATE/logs/${track_id}.log"
  local sentinel_done="$ORCH_STATE/sentinels/${track_id}.done"
  local sentinel_exit="$ORCH_STATE/sentinels/${track_id}.exit-code"

  local wrapped="cd $PROJECT_ROOT && ( $command ) 2>&1 | tee $log_file ; echo \$? > $sentinel_exit ; touch $sentinel_done"

  tmux new-session -d -s "$session" -c "$PROJECT_ROOT" "$wrapped"

  echo "Spawned session: $session"
  echo "Story: $story_key"
  echo "Log: $log_file"
  echo "Attach: tmux attach-session -t $session"
}

cmd_status() {
  local track_id="$1"
  local session
  session=$(session_name "$track_id")
  if tmux has-session -t "$session" 2>/dev/null; then
    echo "running"
    return 0
  else
    echo "not-running"
    return 1
  fi
}

cmd_attach_cmd() {
  local track_id="$1"
  local session
  session=$(session_name "$track_id")
  echo "tmux attach-session -t $session"
}

cmd_kill() {
  local track_id="$1"
  local session
  session=$(session_name "$track_id")
  if tmux has-session -t "$session" 2>/dev/null; then
    tmux kill-session -t "$session"
    echo "Killed: $session"
  else
    echo "Not running: $session"
  fi
}

cmd_list() {
  tmux list-sessions 2>/dev/null | grep "^${SESSION_PREFIX}-" || echo "No track sessions running"
}

cmd_check_exit() {
  local track_id="$1"
  local sentinel_exit="$ORCH_STATE/sentinels/${track_id}.exit-code"
  if [[ -f "$sentinel_exit" ]]; then
    cat "$sentinel_exit"
    return 0
  else
    echo "unknown"
    return 1
  fi
}

cmd_check_done() {
  local track_id="$1"
  local sentinel_done="$ORCH_STATE/sentinels/${track_id}.done"
  if [[ -f "$sentinel_done" ]]; then
    echo "done"
    return 0
  else
    echo "running"
    return 1
  fi
}

cmd_cleanup_sentinels() {
  local track_id="$1"
  rm -f "$ORCH_STATE/sentinels/${track_id}.done" \
        "$ORCH_STATE/sentinels/${track_id}.exit-code" \
        "$ORCH_STATE/sentinels/${track_id}.needs-human"
}

# Dispatch
case "$1" in
  spawn)        shift; cmd_spawn "$@" ;;
  status)       shift; cmd_status "$@" ;;
  attach-cmd)   shift; cmd_attach_cmd "$@" ;;
  kill)         shift; cmd_kill "$@" ;;
  list)         cmd_list ;;
  check-exit)   shift; cmd_check_exit "$@" ;;
  check-done)   shift; cmd_check_done "$@" ;;
  cleanup)      shift; cmd_cleanup_sentinels "$@" ;;
  *)
    echo "Usage: tmux.sh <command> [args]" >&2
    echo "Commands: spawn, status, attach-cmd, kill, list, check-exit, check-done, cleanup" >&2
    exit 2
    ;;
esac
