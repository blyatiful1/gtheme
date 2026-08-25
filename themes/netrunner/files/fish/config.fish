# CachyOS-only base config; guarded so it doesn't error on other distros.
test -f /usr/share/cachyos-fish-config/cachyos-config.fish
and source /usr/share/cachyos-fish-config/cachyos-config.fish

fish_add_path "$HOME/.local/bin"

# ──────────────────────────────────────────────────────────────
#  NETRUNNER — Jack In
#  HUD cyan on navy void · one yellow signature · pink in the veins
#  loaded after CachyOS config
# ──────────────────────────────────────────────────────────────

# Greeting — the Breach Protocol jack-in (skippable; typed-ahead input
# survives). NETRUNNER_JACKIN=off falls back to the static card.
function fish_greeting
    set -l jack $HOME/.local/share/gtheme/assets/netrunner/bin/netrunner-jackin
    if test "$NETRUNNER_JACKIN" != off; and test -x $jack
        $jack
        return
    end
    set_color 10C8D8
    echo '     ▸ ─────────────────────────── ▸'
    set_color --bold 63EDF8
    echo '        N E T R U N N E R // deck online'
    set_color 10C8D8
    echo '     ▸ ─────────────────────────── ▸'
    set_color normal
    set -l qf $HOME/.local/share/gtheme/assets/netrunner/ascii/quotes.txt
    if test -r $qf
        set -l line (shuf -n1 $qf 2>/dev/null)
        if test -n "$line"
            set -l parts (string split --max 1 ' — ' -- $line)
            echo
            set_color --italics 5F7396
            echo -n '        “'$parts[1]'”'
            if set -q parts[2]
                set_color FF2E97
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

# bat — follows the terminal's Netrunner ANSI palette
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

# eza icons everywhere
set -gx EZA_ICONS_AUTO 1

# micro — render exact Netrunner hex colors
set -gx MICRO_TRUECOLOR 1

# fzf — Netrunner palette: cyan HUD on void, yellow pointer, pink marker.
# sharp corners: Night City doesn't do rounded.
set -gx FZF_DEFAULT_OPTS "\
--height 60% --layout=reverse --border sharp --margin=1 --padding=1 \
--color=bg:#0A111F,fg:#D8E7F0,bg+:#14324A,fg+:#F0F9FF \
--color=hl:#10C8D8,hl+:#63EDF8,prompt:#10C8D8,pointer:#FCEE0A \
--color=marker:#FF2E97,info:#5F7396,header:#EE4BA5,border:#19243A \
--color=spinner:#63EDF8 \
--prompt='▸ ' --pointer='❯' --marker='◆' --separator='─' --scrollbar='│'"
type -q fd; and set -gx FZF_DEFAULT_COMMAND 'fd --hidden --strip-cwd-prefix --exclude .git'

# fish syntax highlighting — Netrunner palette
set -g fish_color_command 26D5E5 --bold
set -g fish_color_keyword EE4BA5
set -g fish_color_quote EFDF33
set -g fish_color_error FF3D5E
set -g fish_color_param D8E7F0
set -g fish_color_comment 5F7396 --italics
set -g fish_color_operator 85F2FB
set -g fish_color_end EE4BA5
set -g fish_color_autosuggestion 5F7396
set -g fish_color_valid_path A8F0FA --underline
set -g fish_color_selection --background=14324A
set -g fish_color_search_match --background=14324A

# completion pager — Netrunner
set -g fish_pager_color_progress 0A111F --background=10C8D8
set -g fish_pager_color_prefix 10C8D8
set -g fish_pager_color_description 5F7396

# Deck services — Netrunner terminal toys
function ice --description 'the ICE lamp: lavat cyan glow (also: duo|breach|reactor|street)'
    $HOME/.local/share/gtheme/assets/netrunner/bin/netrunner-ice $argv
end

function breach --description 'ICE breach: dense icy shards'
    $HOME/.local/share/gtheme/assets/netrunner/bin/netrunner-ice breach
end

function reactor --description 'thermal core: gravity churn'
    $HOME/.local/share/gtheme/assets/netrunner/bin/netrunner-ice reactor
end

function jackin --description 'replay the breach greeting + deck vitals'
    $HOME/.local/share/gtheme/assets/netrunner/bin/netrunner-jackin $argv
end

function vitals --description 'deck vitals (alias for jackin)'
    $HOME/.local/share/gtheme/assets/netrunner/bin/netrunner-jackin $argv
end

function visual --description 'the street broadcast (cava)'
    if type -q cava
        cava
    else
        set_color --italics 5F7396
        echo '  no signal on this frequency — install cava.'
        set_color normal
    end
end

function netrun --description 'deck menu'
    if not type -q fzf
        echo 'netrun: fzf not found' >&2
        return 127
    end
    set -l entries \
        'ice      · the ICE lamp — calm cyan glow' \
        'duo      · the lamp in Edgerunners duotone' \
        'breach   · dense icy shards, brisk' \
        'reactor  · gravity churn, thermal core' \
        'jackin   · breach protocol + deck vitals' \
        'fetch    · fastfetch ID card' \
        'visual   · the street broadcast (cava)'
    set -l pick (printf '%s\n' $entries | fzf --prompt='⟁ netrun ▸ ' --height=40% | string split -f1 ' ')
    switch "$pick"
        case ice breach reactor jackin visual
            $pick
        case duo
            ice duo
        case fetch
            fastfetch
        case '*'
            return 0
    end
end
