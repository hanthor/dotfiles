# tailvm bash completion — source this file or add to your shell rc:
#   tailvm completion bash > ~/.tailvm-completion.bash
#   echo 'source ~/.tailvm-completion.bash' >> ~/.bashrc

# tailvm bash completion
_tailvm_completion() {
    local cur prev words cword
    _init_completion || return
    COMPREPLY=($(tailvm _complete bash "${COMP_WORDS[*]}" "$COMP_CWORD"))
}
complete -F _tailvm_completion tailvm

