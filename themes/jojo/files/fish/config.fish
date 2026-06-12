source /usr/share/cachyos-fish-config/cachyos-config.fish

fish_add_path "$HOME/.local/bin"

# ──────────────────────────────────────────────────────────────
#  STONE OCEAN — JoJo's Bizarre Adventure, Part 6 and onwards
#  ocean_abyss · jolyne_green · stone_free blue · spin_gold
#  loaded after CachyOS config
# ──────────────────────────────────────────────────────────────

# Greeting — butterfly + 『STONE OCEAN』 card + one random quote
# (overrides the CachyOS fastfetch greeting; run `fastfetch` manually)
function fish_greeting
    set_color 7DC75B
    echo '  ,   ,'
    echo -n ' { \w/ }    '
    set_color --bold 4FA8E8
    echo '『S T O N E   O C E A N』'
    set_color normal
    set_color 7DC75B
    echo -n '  `>!<`     '
    set_color 9A6BD4
    echo -n 'ゴゴゴ'
    set_color --italics 4A5370
    echo '  yare yare dawa...'
    set_color normal
    set_color 7DC75B
    echo '  (/^\)'
    echo "  '   '"
    set_color normal
    set -l qf $HOME/.local/share/gtheme/themes/jojo/ascii/quotes.txt
    if test -r $qf
        set -l line (shuf -n1 $qf 2>/dev/null)
        if test -n "$line"
            set -l parts (string split --max 1 ' — ' -- $line)
            echo
            set_color --italics 4A5370
            echo -n '  “'$parts[1]'”'
            if set -q parts[2]
                set_color 7DC75B
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

# bat — follows the terminal's Stone Ocean ANSI palette
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

# fzf — Stone Ocean palette
set -gx FZF_DEFAULT_OPTS "\
--height 60% --layout=reverse --border rounded --margin=1 --padding=1 \
--color=bg+:#202741,bg:#0B0E18,spinner:#E8B33F,hl:#E8559A \
--color=fg:#E8EAF2,header:#7DC75B,info:#4A5370,pointer:#7DC75B \
--color=marker:#E8B33F,fg+:#F4F5FB,prompt:#7DC75B,hl+:#FF7AB8 \
--color=border:#202741,label:#E8EAF2,query:#E8EAF2 \
--prompt='❯ ' --marker='❯' --pointer='◆' --separator='─' --scrollbar='│'"
type -q fd; and set -gx FZF_DEFAULT_COMMAND 'fd --hidden --strip-cwd-prefix --exclude .git'

# eza icons everywhere
set -gx EZA_ICONS_AUTO 1

# micro — render exact Stone Ocean hex colors
set -gx MICRO_TRUECOLOR 1

# fish syntax highlighting — Stone Ocean palette
set -g fish_color_command 7DC75B --bold
set -g fish_color_keyword 9A6BD4
set -g fish_color_quote E8B33F
set -g fish_color_error E8435A
set -g fish_color_param E8EAF2
set -g fish_color_comment 4A5370 --italics
set -g fish_color_operator E8559A
set -g fish_color_end 9A6BD4
set -g fish_color_autosuggestion 4A5370
set -g fish_color_valid_path 4FA8E8 --underline
set -g fish_color_selection --background=202741
set -g fish_color_search_match --background=202741

# completion pager — Stone Ocean
set -g fish_pager_color_progress 0B0E18 --background=7DC75B
set -g fish_pager_color_prefix 7DC75B
set -g fish_pager_color_description 4A5370

# Stand abilities — JoJo animation scripts
function menacing --description 'ゴゴゴ menacing rain (any key quits)'
    $HOME/.local/share/gtheme/themes/jojo/bin/jojo-menacing $argv
end
function ora --description 'ORA ORA ORA barrage'
    $HOME/.local/share/gtheme/themes/jojo/bin/jojo-ora $argv
end
function tbc --description 'To Be Continued freeze-frame (any key quits)'
    $HOME/.local/share/gtheme/themes/jojo/bin/jojo-tbc $argv
end
function stand --description 'Stand-stat radar card for a name'
    $HOME/.local/share/gtheme/themes/jojo/bin/jojo-stand $argv
end
