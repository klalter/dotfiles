#!/usr/bin/env bash
# Claude Code statusline — Monokai Pro palette, truecolor ANSI.
# Reads status JSON on stdin, prints one line.

set -u

input="$(cat)"

# ---- Monokai Pro truecolor codes -------------------------------------------------
CYAN="38;2;120;220;232"    # #78DCE8
WHITE="38;2;252;252;250"   # #FCFCFA
PURPLE="38;2;171;157;242"  # #AB9DF2
PINK="38;2;255;97;136"     # #FF6188
GREEN="38;2;169;220;118"   # #A9DC76
YELLOW="38;2;255;216;102"  # #FFD866
ORANGE="38;2;252;152;103"  # #FC9867
RED="38;2;255;97;89"       # #FF6159
GRAY="38;2;140;140;140"
SEP="38;2;114;112;114"     # #727072

jqr() { printf '%s' "$input" | jq -r "$1" 2>/dev/null; }

# ---- Bucket color for a percentage -----------------------------------------------
bucket_color() {
  local pct="$1"
  awk -v p="$pct" 'BEGIN {
    if (p < 50) print "'"$GREEN"'";
    else if (p < 75) print "'"$YELLOW"'";
    else if (p < 90) print "'"$ORANGE"'";
    else print "'"$RED"'";
  }'
}

cwd="$(jqr '.cwd // empty')"
[ -z "$cwd" ] && cwd="$(pwd)"

# ---- Git context (computed once) --------------------------------------------------
is_git_repo="false"
git_dir_abs=""
common_dir_abs=""

if git --no-optional-locks -C "$cwd" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  is_git_repo="true"
  gd="$(git --no-optional-locks -C "$cwd" rev-parse --git-dir 2>/dev/null)"
  cd_="$(git --no-optional-locks -C "$cwd" rev-parse --git-common-dir 2>/dev/null)"
  if [ -n "$gd" ]; then
    case "$gd" in
      /*) : ;;
      *) gd="$cwd/$gd" ;;
    esac
    git_dir_abs="$(realpath -m "$gd" 2>/dev/null)"
  fi
  if [ -n "$cd_" ]; then
    case "$cd_" in
      /*) : ;;
      *) cd_="$cwd/$cd_" ;;
    esac
    common_dir_abs="$(realpath -m "$cd_" 2>/dev/null)"
  fi
fi

segments=()

# ================================================================================
# 1. REPO NAME
# ================================================================================
repo_name="$(jqr '.workspace.repo.name // empty')"

if [ -z "$repo_name" ] && [ -n "$common_dir_abs" ]; then
  parent_dir="$(dirname "$common_dir_abs")"
  repo_name="$(basename "$parent_dir")"
fi

if [ -z "$repo_name" ]; then
  project_dir="$(jqr '.workspace.project_dir // empty')"
  if [ -n "$project_dir" ]; then
    repo_name="$(basename "$project_dir")"
  else
    repo_name="$(basename "$cwd")"
  fi
fi

if [ -n "$repo_name" ]; then
  seg="$(printf '\033[1;%sm%s\033[0m' "$CYAN" "$repo_name")"
  segments+=("$seg")
fi

# ================================================================================
# 2. BRANCH (only if in a git repo)
# ================================================================================
if [ "$is_git_repo" = "true" ]; then
  branch="$(git --no-optional-locks -C "$cwd" symbolic-ref --short HEAD 2>/dev/null)"
  if [ -z "$branch" ]; then
    branch="$(git --no-optional-locks -C "$cwd" rev-parse --short HEAD 2>/dev/null)"
  fi

  if [ -n "$branch" ]; then
    blen=${#branch}
    if [ "$blen" -gt 13 ]; then
      branch="${branch:0:8}…${branch: -4}"
    fi

    prefix=""
    if [ -n "$git_dir_abs" ] && [ -n "$common_dir_abs" ] && [ "$git_dir_abs" != "$common_dir_abs" ]; then
      prefix="$(printf '\033[%sm↳ \033[0m' "$WHITE")"
    fi

    seg="${prefix}$(printf '\033[%sm⎇\033[0m \033[%sm(%s)\033[0m' "$WHITE" "$PURPLE" "$branch")"
    segments+=("$seg")
  fi
fi

# ================================================================================
# 3. MODEL
# ================================================================================
model_name="$(jqr '.model.display_name // .model.id // empty')"

if [ -n "$model_name" ]; then
  lname="$(printf '%s' "$model_name" | tr '[:upper:]' '[:lower:]')"
  case "$lname" in
    *opus*) initial="O" ;;
    *sonnet*) initial="S" ;;
    *haiku*) initial="H" ;;
    *fable*) initial="F" ;;
    *) initial="$model_name" ;;
  esac

  seg="$(printf '\033[%sm*\033[0m \033[%sm%s\033[0m' "$GRAY" "$PINK" "$initial")"

  effort="$(jqr '.effort.level // empty')"
  if [ -n "$effort" ]; then
    case "$effort" in
      low) ecolor="$GRAY" ;;
      medium) ecolor="$GREEN" ;;
      high) ecolor="$YELLOW" ;;
      xhigh) ecolor="$ORANGE" ;;
      max) ecolor="$RED" ;;
      *) ecolor="" ;;
    esac
    if [ -n "$ecolor" ]; then
      seg="${seg}$(printf ' \033[%sm●\033[0m' "$ecolor")"
    fi
  fi

  segments+=("$seg")
fi

# ================================================================================
# 4. CONTEXT GAUGE
# ================================================================================
used_pct="$(jqr '.context_window.used_percentage // empty')"

if [ -z "$used_pct" ]; then
  transcript_path="$(jqr '.transcript_path // empty')"
  window_size="$(jqr '.context_window.context_window_size // empty')"
  model_id="$(jqr '.model.id // empty')"

  if [ -z "$window_size" ]; then
    case "$model_id" in
      *1m*) window_size=1000000 ;;
      *) window_size=200000 ;;
    esac
  fi

  if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
    usage_json="$(tac "$transcript_path" 2>/dev/null | grep -m1 '"usage"')"
    if [ -n "$usage_json" ]; then
      usage_obj="$(printf '%s' "$usage_json" | jq -c 'if .message.usage then .message.usage elif .usage then .usage else empty end' 2>/dev/null)"
      if [ -n "$usage_obj" ] && [ "$usage_obj" != "null" ]; then
        in_tok="$(printf '%s' "$usage_obj" | jq -r '.input_tokens // 0' 2>/dev/null)"
        cr_tok="$(printf '%s' "$usage_obj" | jq -r '.cache_read_input_tokens // 0' 2>/dev/null)"
        cc_tok="$(printf '%s' "$usage_obj" | jq -r '.cache_creation_input_tokens // 0' 2>/dev/null)"
        used_pct="$(awk -v i="$in_tok" -v r="$cr_tok" -v c="$cc_tok" -v w="$window_size" 'BEGIN { if (w > 0) printf "%.0f", (i+r+c)/w*100; else print "" }')"
      fi
    fi
  fi
fi

if [ -n "$used_pct" ]; then
  ccolor="$(bucket_color "$used_pct")"
  pct_int="$(awk -v p="$used_pct" 'BEGIN { printf "%.0f", p }')"
  seg="$(printf '\033[%sm>\033[0m \033[%sm●\033[0m %s%%' "$GRAY" "$ccolor" "$pct_int")"
else
  seg="$(printf '\033[%sm> ● ?\033[0m' "$GRAY")"
fi
segments+=("$seg")

# ================================================================================
# 5. SESSION LIMIT GAUGE (only if present)
# ================================================================================
five_pct="$(jqr '.rate_limits.five_hour.used_percentage // empty')"
resets_at="$(jqr '.rate_limits.five_hour.resets_at // empty')"

if [ -n "$five_pct" ] && [ -n "$resets_at" ]; then
  scolor="$(bucket_color "$five_pct")"
  spct_int="$(awk -v p="$five_pct" 'BEGIN { printf "%.0f", p }')"

  now="$(date +%s)"
  diff=$(( resets_at - now ))
  if [ "$diff" -lt 0 ]; then diff=0; fi
  minutes=$(( diff / 60 ))

  if [ "$minutes" -ge 60 ]; then
    hours=$(( minutes / 60 ))
    remm=$(( minutes % 60 ))
    countdown="${hours}h ${remm}m"
  else
    countdown="${minutes}m"
  fi

  seg="$(printf '\033[%sm~\033[0m \033[%sm●\033[0m %s%% \033[%sm->\033[0m %s' "$GRAY" "$scolor" "$spct_int" "$GRAY" "$countdown")"
  segments+=("$seg")
fi

# ================================================================================
# Join and print
# ================================================================================
sep="$(printf ' \033[%sm|\033[0m ' "$SEP")"

out=""
for i in "${!segments[@]}"; do
  if [ "$i" -gt 0 ]; then
    out="${out}${sep}"
  fi
  out="${out}${segments[$i]}"
done

printf '%s\n' "$out"
