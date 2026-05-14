if status is-interactive
    # Suppress the default greeting
    set -g fish_greeting ""

    # PATH extras (prepend so brew/local bins win)
    fish_add_path -m ~/.local/bin
    fish_add_path -m ~/.cargo/bin

    # Environment
    set -gx EDITOR nvim
    set -gx VISUAL nvim
    set -gx PAGER delta
    set -gx MANPAGER "sh -c 'col -bx | bat -l man -p'"
    set -gx XDG_CONFIG_HOME ~/.config
    set -gx XDG_DATA_HOME ~/.local/share
    set -gx XDG_CACHE_HOME ~/.cache
    set -gx XDG_STATE_HOME ~/.local/state

    # bluefin-cli shell integration (bling + init: eza, bat, zoxide, starship, atuin, fzf)
    set -l bling "$HOME/.local/share/bluefin-cli/bling/bling.fish"
    test -f "$bling" && source "$bling"
    command -q bluefin-cli && bluefin-cli init fish | source

    # direnv
    command -q direnv && direnv hook fish | source

    # fzf keybindings (fallback if bluefin-cli didn't set them up)
    if command -q fzf && not functions -q _fzf_search_history
        fzf --fish | source
    end
end
