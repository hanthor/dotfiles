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

# ── tmux ─────────────────────────────────────────────────────────
abbr --add ta 'tmux a'

# ── Claude Code ──────────────────────────────────────────────────
abbr --add claude-yolo 'claude --dangerously-skip-permissions'

# ── Tailscale exit-node toggle (Mullvad Singapore) ──────────────
if command -q tailscale
    abbr --add ts-exit-sg  'tailscale set --exit-node=sg-sin-wg-001.mullvad.ts.net'
    abbr --add ts-exit-off 'tailscale set --exit-node='
end

# ── Typo corrections (found via atuin exit=127 + raw shell history) ─
abbr --add jsut       just
abbr --add jusr       just
abbr --add justfg     just
abbr --add tmuz       tmux
abbr --add tmus       tmux
abbr --add tmix       tmux
abbr --add rmux       tmux
abbr --add sudoc      sudo
abbr --add podmand    podman
abbr --add pii        pi
abbr --add ssk-keygen ssh-keygen
abbr --add exut       exit
abbr --add got        git
abbr --add uups       uupd
abbr --add brewinstall 'brew install'

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
