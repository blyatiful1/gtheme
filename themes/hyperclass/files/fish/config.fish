# CachyOS-only base config; guarded so it doesn't error on other distros.
test -f /usr/share/cachyos-fish-config/cachyos-config.fish
and source /usr/share/cachyos-fish-config/cachyos-config.fish

fish_add_path "$HOME/.local/bin"

# ──────────────────────────────────────────────────────────────
#  HYPERCLASS — Gilded Void
#  champagne brass on deep-space ink · one vein of ice
#  loaded after CachyOS config
# ──────────────────────────────────────────────────────────────

# Greeting — a small boarding-lounge card + one random quote
# (overrides the CachyOS fastfetch greeting; run `fastfetch` manually)
function fish_greeting
    set_color C9A24A
    echo '     ✦ ═══════════════════════ ✦'
    set_color --bold EBD9A8
    echo '       『 G I L D E D   V O I D 』'
    set_color C9A24A
    echo '     ◆ ─────────────────────── ◆'
    set_color normal
    set_color --italics 6E7488
    echo '        now boarding — first class to anywhere.'
    set_color normal
    set -l qf $HOME/.local/share/gtheme/assets/hyperclass/ascii/quotes.txt
    if test -r $qf
        set -l line (shuf -n1 $qf 2>/dev/null)
        if test -n "$line"
            set -l parts (string split --max 1 ' — ' -- $line)
            echo
            set_color --italics 6E7488
            echo -n '        “'$parts[1]'”'
            if set -q parts[2]
                set_color C9A24A
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

# bat — follows the terminal's Gilded Void ANSI palette
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

# micro — render exact Gilded Void hex colors
set -gx MICRO_TRUECOLOR 1

# fzf — Gilded Void palette: brass trim on ink, one vein of ice for the header
set -gx FZF_DEFAULT_OPTS "\
--height 60% --layout=reverse --border rounded --margin=1 --padding=1 \
--color=bg:#12151F,fg:#EAE3D1,bg+:#2A3046,fg+:#FBF6E7 \
--color=hl:#C9A24A,hl+:#E9CD8A,prompt:#C9A24A,pointer:#C9A24A \
--color=marker:#EBD9A8,info:#6E7488,header:#8FC6D8,border:#232838 \
--color=spinner:#EBD9A8 \
--prompt='✦ ' --pointer='❯' --marker='◆' --separator='─' --scrollbar='│'"
type -q fd; and set -gx FZF_DEFAULT_COMMAND 'fd --hidden --strip-cwd-prefix --exclude .git'

# fish syntax highlighting — Gilded Void palette
set -g fish_color_command C9A24A --bold
set -g fish_color_keyword B79BE0
set -g fish_color_quote EBD9A8
set -g fish_color_error E2707F
set -g fish_color_param EAE3D1
set -g fish_color_comment 6E7488 --italics
set -g fish_color_operator 8FC6D8
set -g fish_color_end B79BE0
set -g fish_color_autosuggestion 6E7488
set -g fish_color_valid_path A9DAE8 --underline
set -g fish_color_selection --background=2A3046
set -g fish_color_search_match --background=2A3046

# completion pager — Gilded Void
set -g fish_pager_color_progress 12151F --background=C9A24A
set -g fish_pager_color_prefix C9A24A
set -g fish_pager_color_description 6E7488

# Cabin service — Gilded Void terminal toys
function orrery --description 'the brass planetarium clock (any key quits)'
    $HOME/.local/share/gtheme/assets/hyperclass/bin/hyperclass-orrery $argv
end

function warp --description 'engage hyperspace (any key quits)'
    $HOME/.local/share/gtheme/assets/hyperclass/bin/hyperclass-warp $argv
end

function boarding --description 'print your boarding pass'
    $HOME/.local/share/gtheme/assets/hyperclass/bin/hyperclass-boarding $argv
end

function lounge --description 'the house band (cava)'
    if type -q cava
        cava
    else
        set_color --italics 6E7488
        echo '  the house band is not aboard this voyage — install cava.'
        set_color normal
    end
end
