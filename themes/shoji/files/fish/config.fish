# CachyOS-only base config; guarded so it doesn't error on other distros.
test -f /usr/share/cachyos-fish-config/cachyos-config.fish
and source /usr/share/cachyos-fish-config/cachyos-config.fish

fish_add_path "$HOME/.local/bin"

# ──────────────────────────────────────────────────────────────
#  SHOJI — Paper & Ink
#  washi #F2EFE5 · sumi #33302A · vermilion #B3402E
#  loaded after CachyOS config
# ──────────────────────────────────────────────────────────────

# Starship prompt (defined last so it wins the prompt)
if type -q starship
    starship init fish | source
end

# bat — follows the terminal's Shoji ANSI palette
set -gx BAT_THEME "ansi"
if type -q bat
    alias cat='bat --style=plain --paging=never'
    alias catn='bat'                      # cat with line numbers + git gutter
    function help --description 'colorized --help'
        $argv --help 2>&1 | bat --plain --language=help
    end
end

# fd preferred over find; eza tree shortcut (ls/la/ll/lt come from CachyOS)
type -q fd; and alias find='fd'
type -q eza; and alias tree='eza --tree --icons --group-directories-first'

# fzf — Shoji paper palette
set -gx FZF_DEFAULT_OPTS "\
--height 60% --layout=reverse --border rounded --margin=1 --padding=1 \
--color=bg+:#E7DBB7,bg:#F2EFE5,spinner:#977119,hl:#B3402E \
--color=fg:#33302A,header:#B3402E,info:#6E6857,pointer:#B3402E \
--color=marker:#977119,fg+:#1C1A15,prompt:#B3402E,hl+:#D0543B \
--color=border:#D2CAB4,label:#33302A,query:#33302A \
--prompt='❯ ' --marker='❯' --pointer='◆' --separator='─' --scrollbar='│'"
type -q fd; and set -gx FZF_DEFAULT_COMMAND 'fd --hidden --strip-cwd-prefix --exclude .git'

# eza icons everywhere
set -gx EZA_ICONS_AUTO 1

# micro — render exact Shoji hex colors
set -gx MICRO_TRUECOLOR 1

# fish syntax highlighting — sumi ink on washi
set -g fish_color_command 1C1A15 --bold
set -g fish_color_keyword B3402E
set -g fish_color_quote 5F7A38
set -g fish_color_error D0543B
set -g fish_color_param 33302A
set -g fish_color_comment 9A9382 --italics
set -g fish_color_operator B3402E
set -g fish_color_autosuggestion 9A9382
set -g fish_color_valid_path --underline
set -g fish_color_selection --background=E7DBB7
set -g fish_color_search_match --background=E7DBB7

# completion pager — Shoji
set -g fish_pager_color_progress FBF9F2 --background=B3402E
set -g fish_pager_color_prefix B3402E
set -g fish_pager_color_description 6E6857
