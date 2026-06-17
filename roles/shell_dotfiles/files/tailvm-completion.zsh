# tailvm zsh completion — source this file or add to your shell rc:
#   tailvm completion zsh > ~/.tailvm-completion.zsh
#   echo 'source ~/.tailvm-completion.zsh' >> ~/.zshrc

#compdef tailvm
# tailvm zsh completion
_tailvm() {
    local -a completions
    completions=(${(f)"$(tailvm _complete zsh "${words[*]}" "$CURRENT")"})
    compadd -a completions
}
_tailvm

