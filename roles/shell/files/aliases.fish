# Shared aliases for fish — managed by Ansible
# NOTE: bluefin-cli init handles: eza/ll/ls, bat/cat, ugrep/grep,
#       zoxide/cd, starship, atuin, fzf — do NOT duplicate those here

# vim → nvim
if command -q nvim
    alias vim 'nvim'
    alias vi 'nvim'
end

# Navigation
alias .. 'cd ..'
alias ... 'cd ../..'
alias .... 'cd ../../..'

# Git
alias gs 'git status'
alias ga 'git add'
alias gaa 'git add -A'
alias gc 'git commit'
alias gcm 'git commit -m'
alias gca 'git commit --amend'
alias gp 'git push'
alias gpf 'git push --force-with-lease'
alias gl 'git log --oneline --graph -20'
alias gd 'git diff'
alias gds 'git diff --staged'
alias gco 'git checkout'
alias gb 'git branch'
alias gpl 'git pull'
alias gst 'git stash'
alias gstp 'git stash pop'

# Kubernetes
if command -q kubectl
    alias k 'kubectl'
    alias kgp 'kubectl get pods'
    alias kgs 'kubectl get svc'
    alias kgn 'kubectl get nodes'
    alias kd 'kubectl describe'
    alias kl 'kubectl logs'
    alias klf 'kubectl logs -f'
    alias kx 'kubectl exec -it'
end

# Podman
alias dc 'podman compose'
alias dps 'podman ps'
alias dpsa 'podman ps -a'

# Misc
alias reload 'exec fish'
alias path 'string split ":" $PATH'
alias myip 'curl -s ifconfig.me'
alias cls 'clear'
alias h 'history'
alias md 'mkdir -p'
if command -q trash
    alias rm 'trash'
end
