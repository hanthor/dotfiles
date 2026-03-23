if status is-interactive
    # bluefin-cli shell integration (bling + init)
    set -l bling "$HOME/.local/share/bluefin-cli/bling/bling.fish"
    test -f "$bling" && source "$bling"
    command -q bluefin-cli && bluefin-cli init fish | source
end
