# CachyOS-only base config; guarded so it doesn't error on other distros.
test -f /usr/share/cachyos-fish-config/cachyos-config.fish
and source /usr/share/cachyos-fish-config/cachyos-config.fish

fish_add_path "$HOME/.local/bin"

# ──────────────────────────────────────────────────────────────
#  MAGMA — Obsidian Flow
#  obsidian glass · molten orange · lava gold · one teal vein
#  loaded after CachyOS config
# ──────────────────────────────────────────────────────────────

# Greeting — a small vent + 『OBSIDIAN FLOW』 card + one random quote
# (overrides the CachyOS fastfetch greeting; run `fastfetch` manually)
function fish_greeting
    set_color FF6D3A
    echo '     ▂▃▂'
    echo -n '    ▟█▓█▙    '
    set_color --bold FFC145
    echo '『O B S I D I A N   F L O W』'
    set_color normal
    set_color E0304E
    echo -n '   ▄██▓██▄   '
    set_color FFA05C
    echo -n '  ⋯'
    set_color --italics 7A6470
    echo '  the chamber is awake.'
    set_color normal
    set_color 3A2030
    echo '  ▄███████▄'
    echo ' ▔▔▔▔▔▔▔▔▔▔▔'
    set_color normal
    set -l qf $HOME/.local/share/gtheme/assets/magma/ascii/quotes.txt
    if test -r $qf
        set -l line (shuf -n1 $qf 2>/dev/null)
        if test -n "$line"
            set -l parts (string split --max 1 ' — ' -- $line)
            echo
            set_color --italics 7A6470
            echo -n '  “'$parts[1]'”'
            if set -q parts[2]
                set_color FF6D3A
                echo -n '  — '$parts[2]
            end
            set_color normal
            echo
        end
    end
end

# Starship prompt (defined last so it wins the prompt)
if type -q starship
    starship init fish | source
end

# bat — follows the terminal's Obsidian Flow ANSI palette
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

# fzf — Obsidian Flow palette
set -gx FZF_DEFAULT_OPTS "\
--height 60% --layout=reverse --border rounded --margin=1 --padding=1 \
--color=bg+:#3A2030,bg:#0D0A0F,spinner:#FFC145,hl:#E0304E \
--color=fg:#F2E5D5,header:#FF6D3A,info:#7A6470,pointer:#FF6D3A \
--color=marker:#FFC145,fg+:#FFF6E8,prompt:#FF6D3A,hl+:#FF7A6E \
--color=border:#261826,label:#F2E5D5,query:#F2E5D5 \
--prompt='❯ ' --marker='❯' --pointer='◆' --separator='─' --scrollbar='│'"
type -q fd; and set -gx FZF_DEFAULT_COMMAND 'fd --hidden --strip-cwd-prefix --exclude .git'

# eza icons everywhere
set -gx EZA_ICONS_AUTO 1

# micro — render exact Obsidian Flow hex colors
set -gx MICRO_TRUECOLOR 1

# fish syntax highlighting — Obsidian Flow palette
set -g fish_color_command FF6D3A --bold
set -g fish_color_keyword B07BE8
set -g fish_color_quote FFC145
set -g fish_color_error F25050
set -g fish_color_param F2E5D5
set -g fish_color_comment 7A6470 --italics
set -g fish_color_operator E0304E
set -g fish_color_end B07BE8
set -g fish_color_autosuggestion 7A6470
set -g fish_color_valid_path 45C7B5 --underline
set -g fish_color_selection --background=3A2030
set -g fish_color_search_match --background=3A2030

# completion pager — Obsidian Flow
set -g fish_pager_color_progress 0D0A0F --background=FF6D3A
set -g fish_pager_color_prefix FF6D3A
set -g fish_pager_color_description 7A6470

# Chamber controls — Magma animation scripts
function lavalamp --description 'live metaball lava lamp (any key quits)'
    $HOME/.local/share/gtheme/assets/magma/bin/magma-lavalamp $argv
end
function embers --description 'rising ember drift (any key quits)'
    $HOME/.local/share/gtheme/assets/magma/bin/magma-embers $argv
end
function erupt --description '~3.5s eruption, then back to work'
    $HOME/.local/share/gtheme/assets/magma/bin/magma-eruption $argv
end
function thermal --description 'thermal-scan gauge card for a name'
    $HOME/.local/share/gtheme/assets/magma/bin/magma-thermal $argv
end
