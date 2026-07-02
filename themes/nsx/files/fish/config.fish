# CachyOS-only base config; guarded so it doesn't error on other distros.
test -f /usr/share/cachyos-fish-config/cachyos-config.fish
and source /usr/share/cachyos-fish-config/cachyos-config.fish

# overwrite greeting
# potentially disabling fastfetch
#function fish_greeting
#    # smth smth
#end
fish_add_path "$HOME/.local/bin"

# ──────────────────────────────────────────────────────────────
#  Honda NSX NA1 — Precision Crafted Performance
#  Berlina black · Formula Red · Championship White
#  loaded after CachyOS config
# ──────────────────────────────────────────────────────────────

# Starship prompt (defined last so it wins the prompt)
if type -q starship
    starship init fish | source
end

# bat — follows the terminal's NSX ANSI palette
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

# fzf — NSX Formula palette
set -gx FZF_DEFAULT_OPTS "\
--height 60% --layout=reverse --border rounded --margin=1 --padding=1 \
--color=bg+:#222327,bg:#0D0D0F,spinner:#E89C3F,hl:#F04A3E \
--color=fg:#E8E9DF,header:#D2241E,info:#AEB2B5,pointer:#D2241E \
--color=marker:#E89C3F,fg+:#F2F3EA,prompt:#D2241E,hl+:#F04A3E \
--color=border:#50535A,label:#E8E9DF,query:#E8E9DF \
--prompt='❯ ' --marker='❯' --pointer='◆' --separator='─' --scrollbar='│'"
type -q fd; and set -gx FZF_DEFAULT_COMMAND 'fd --hidden --strip-cwd-prefix --exclude .git'

# eza icons everywhere
set -gx EZA_ICONS_AUTO 1

# micro — render exact NSX hex colors
set -gx MICRO_TRUECOLOR 1

# fish syntax highlighting — NSX Formula palette
set -g fish_color_command F2F3EA --bold
set -g fish_color_keyword F04A3E
set -g fish_color_quote E89C3F
set -g fish_color_error F04A3E
set -g fish_color_param C9CBC0
set -g fish_color_comment 50535A --italics
set -g fish_color_operator D2241E
set -g fish_color_autosuggestion 50535A
set -g fish_color_valid_path --underline
set -g fish_color_selection --background=3E2422
set -g fish_color_search_match --background=3E2422

# completion pager — NSX
set -g fish_pager_color_progress F2F3EA --background=D2241E
set -g fish_pager_color_prefix D2241E
set -g fish_pager_color_description C9CBC0
