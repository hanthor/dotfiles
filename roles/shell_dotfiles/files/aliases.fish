# Fish abbreviations + aliases — managed by Ansible
# Abbreviations expand visually on space so you see (and learn) the real command.
# NOTE: bluefin-cli init handles: eza/ll/ls, bat/cat, ugrep/grep,
#       zoxide/cd, starship, atuin, fzf — do NOT duplicate those here

# ── vim → nvim ───────────────────────────────────────────────────
if command -q nvim
    alias vim nvim
    alias vi nvim
    alias v nvim
end

# ── Navigation ───────────────────────────────────────────────────
abbr --add -- .. 'cd ..'
abbr --add -- ... 'cd ../..'
abbr --add -- .... 'cd ../../..'

# ── Git abbreviations ────────────────────────────────────────────
abbr --add gs   'git status -sb'
abbr --add ga   'git add'
abbr --add gaa  'git add -A'
abbr --add gc   'git commit'
abbr --add gcm  'git commit -m'
abbr --add gca  'git commit --amend --no-edit'
abbr --add gp   'git push'
abbr --add gpf  'git push --force-with-lease'
abbr --add gl   'git log --oneline --graph --decorate -20'
abbr --add gla  'git log --oneline --graph --decorate --all'
abbr --add gd   'git diff'
abbr --add gds  'git diff --staged'
abbr --add gco  'git checkout'
abbr --add gb   'git branch -vv'
abbr --add gpl  'git pull'
abbr --add gst  'git stash'
abbr --add gstp 'git stash pop'

# ── Kubernetes abbreviations ─────────────────────────────────────
if command -q kubectl
    abbr --add k    kubectl
    abbr --add kgp  'kubectl get pods'
    abbr --add kgpa 'kubectl get pods -A'
    abbr --add kgs  'kubectl get svc'
    abbr --add kgn  'kubectl get nodes'
    abbr --add kd   'kubectl describe'
    abbr --add kl   'kubectl logs'
    abbr --add klf  'kubectl logs -f'
    abbr --add kx   'kubectl exec -it'
end

# ── Podman abbreviations ─────────────────────────────────────────
abbr --add dc    'podman compose'
abbr --add dps   'podman ps'
abbr --add dpsa  'podman ps -a'
abbr --add dexec 'podman exec -it'
abbr --add dlogs 'podman logs -f'

# ── Dotfiles ─────────────────────────────────────────────────────
abbr --add dots       'cd ~/.local/share/dotfiles; and git pull --ff-only; and just apply --skip-tags secrets'
abbr --add dots-apply 'cd ~/.local/share/dotfiles; and git pull --ff-only; and just apply'

# ── Misc ─────────────────────────────────────────────────────────
abbr --add reload  'exec fish -l'
abbr --add path    'string split : $PATH'
abbr --add myip    'curl -s ifconfig.me; and echo'
abbr --add cls     clear
abbr --add md      'mkdir -p'
abbr --add h       history

if command -q trash
    alias rm trash
end
