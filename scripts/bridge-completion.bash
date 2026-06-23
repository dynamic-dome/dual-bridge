# Completion for dual-bridge lane names and bridge commands.
#
# Load with:
#   source scripts/bridge-completion.bash

_DUAL_BRIDGE_COMPLETION_WORDS="lane-A-to-B lane-B-to-A handoff_write handoff_poll handoff_collect"

if [ -n "${ZSH_VERSION:-}" ]; then
  autoload -Uz compinit
  if ! whence -w compdef >/dev/null 2>&1; then
    compinit
  fi

  _dual_bridge_completion() {
    local -a matches
    matches=(lane-A-to-B lane-B-to-A handoff_write handoff_poll handoff_collect)
    compadd -- "${matches[@]}"
  }

  compdef _dual_bridge_completion handoff_write handoff_poll handoff_collect \
    handoff_write.py handoff_poll.py handoff_collect.py
elif [ -n "${BASH_VERSION:-}" ]; then
  _dual_bridge_completion() {
    local cur
    cur="${COMP_WORDS[COMP_CWORD]}"
    COMPREPLY=($(compgen -W "${_DUAL_BRIDGE_COMPLETION_WORDS}" -- "${cur}"))
  }

  complete -F _dual_bridge_completion handoff_write handoff_poll handoff_collect \
    handoff_write.py handoff_poll.py handoff_collect.py
fi
