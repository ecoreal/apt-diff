# bash completion for apt-diff
_apt_diff() {
    local cur prev commands opts
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    commands="init snapshot diff check log show prune"
    opts="--store --root --json --no-color --quiet --version --help --keep --against --etc-max -n -q"

    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
        return 0
    fi

    local cmd="${COMP_WORDS[1]}"
    case "$cmd" in
        diff|show|check)
            if [ "$prev" = "diff" ] || [ "$prev" = "show" ]; then
                # complete snapshot names (timestamps) from the store
                local store="${APTDIFF_STORE:-/var/lib/apt-diff}"
                [ -d "$store" ] || store="$HOME/.local/share/apt-diff"
                local names=""
                if [ -d "$store" ]; then
                    names=$(ls "$store" 2>/dev/null | sed -n 's/^snapshot-\([0-9T]*\)\.json\.gz$/\1/p')
                fi
                COMPREPLY=( $(compgen -W "latest baseline $names" -- "$cur") )
            else
                COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
            fi
            ;;
        prune|snapshot)
            COMPREPLY=( $(compgen -W "--keep $opts" -- "$cur") )
            ;;
        *)
            COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
            ;;
    esac
    return 0
}
complete -F _apt_diff apt-diff
