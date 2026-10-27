#!/usr/bin/env bash
# Native PipeWire DSP and the user-session microphone routing service.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if skipped_by_profile skip_pipewire_audio; then
  note "SKIPPED: skip_pipewire_audio / vm-test"
  finish
fi
# is_desktop silently treats a missing or broken yq as a non-desktop. Only
# consult inventory when neither the environment nor host_vars decides it.
desktop="${DOTFILES_IS_DESKTOP:-$(host_var is_desktop)}"
case "$desktop" in
  1|true) ;;
  0|false) note "SKIPPED: not a desktop"; finish ;;
  '')
    if ! command -v yq >/dev/null 2>&1; then
      step "desktop inventory requires yq" false
      finish
    fi
    desktop="$(yq ".all.children.desktop.hosts | has(\"$MACHINE\")" "$DOTFILES_DIR/inventory.yml")" || {
      step "read desktop inventory" false
      finish
    }
    case "$desktop" in
      true) ;;
      false) note "SKIPPED: not a desktop"; finish ;;
      *) step "invalid desktop inventory result" false; finish ;;
    esac
    ;;
  *) step "invalid is_desktop override" false; finish ;;
esac

assets="$DOTFILES_DIR/units/pipewire-audio"
conf="$HOME/.config/pipewire/pipewire.conf.d"
user_systemd="$HOME/.config/systemd/user"
state="$HOME/.local/state/pipewire-audio"
# The unit default and flat group/host variables remain the source of truth.
flat_var() {
  local value
  value="$(sed -n "s/^$2:[[:space:]]*\([^#]*[^#[:space:]]\).*/\1/p" "$1" 2>/dev/null | head -n1)"
  value="${value//[\"\']/}"
  printf '%s' "$value"
}
resolve_mic_volume() {
  local value group file membership present
  value="${MIC_HARDWARE_VOLUME_PCT:-$(host_var mic_hardware_volume_pct)}"
  if [ -n "$value" ]; then printf '%s' "$value"; return 0; fi
  [ -r "$assets/defaults/main.yml" ] || return 1
  value="$(flat_var "$assets/defaults/main.yml" mic_hardware_volume_pct)"
  [ -n "$value" ] || return 1
  file="$DOTFILES_DIR/group_vars/all.yml"
  if [ -f "$file" ]; then
    group="$(flat_var "$file" mic_hardware_volume_pct)"
    [ -z "$group" ] || value="$group"
  fi
  for file in "$DOTFILES_DIR"/group_vars/*.yml; do
    [ -f "$file" ] || continue
    group="${file##*/}"; group="${group%.yml}"
    [ "$group" != all ] || continue
    membership="$(flat_var "$file" mic_hardware_volume_pct)"
    [ -n "$membership" ] || continue
    if [ "$group" = desktop ]; then
      value="$membership"
    else
      command -v yq >/dev/null 2>&1 || { note "mic_hardware_volume_pct in group $group requires yq" >&2; return 1; }
      present="$(yq ".all.children[\"$group\"].hosts | has(\"$MACHINE\")" "$DOTFILES_DIR/inventory.yml")" || return 1
      case "$present" in
        true) value="$membership" ;;
        false) ;;
        *) note "unable to resolve group $group membership" >&2; return 1 ;;
      esac
    fi
  done
  printf '%s' "$value"
}
if ! mic_volume="$(resolve_mic_volume)"; then
  step "resolve mic_hardware_volume_pct" false
  finish
fi
# The volume is substituted into a shell command in a systemd unit.
if [[ ! "$mic_volume" =~ ^[0-9]{1,3}$ ]] || (( 10#$mic_volume > 100 )); then
  step "invalid mic_hardware_volume_pct (expected 0-100)" false
  finish
fi

as_root() {
  if [ "$(id -u)" = 0 ]; then "$@"; else sudo -n "$@"; fi
}

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  check_audio_packages() {
    local os_id="" os_like="" pkg result rc manager=0
    if [ -r /etc/os-release ]; then
      os_id="$(. /etc/os-release; printf '%s' "${ID:-}")"
      os_like="$(. /etc/os-release; printf '%s' "${ID_LIKE:-}")"
    fi
    if command -v dnf >/dev/null 2>&1 || command -v rpm-ostree >/dev/null 2>&1; then
      manager=1
      command -v rpm >/dev/null 2>&1 || { note "FAIL  rpm required to inspect DSP packages"; return 1; }
      for pkg in lsp-plugins-lv2 noise-suppression-for-voice; do
        result="$(LC_ALL=C rpm -q "$pkg" 2>&1)"; rc=$?
        if [ "$rc" = 0 ]; then :
        elif [ "$rc" = 1 ] && [ "$result" = "package $pkg is not installed" ]; then
          note "WOULD install DSP package $pkg"
        else
          note "FAIL  inspect DSP package $pkg"; return 1
        fi
      done
    fi
    if [[ " $os_id $os_like " == *" arch "* ]]; then
      manager=1
      command -v pacman >/dev/null 2>&1 || { note "FAIL  pacman required to inspect DSP packages"; return 1; }
      for pkg in lsp-plugins noise-suppression-for-voice; do
        result="$(LC_ALL=C pacman -Q "$pkg" 2>&1)"; rc=$?
        if [ "$rc" = 0 ]; then :
        elif [ "$rc" = 1 ] && [ "$result" = "error: package '$pkg' was not found" ]; then
          note "WOULD install DSP package $pkg"
        else
          note "FAIL  inspect DSP package $pkg"; return 1
        fi
      done
    fi
    if [ "$manager" = 0 ]; then
      note "PARTIAL: DSP package prerequisites must be inspected for this distribution"
    fi
  }

  # Return 0 for equal bytes, 1 for different, and 2 for an inspection error.
  check_compare() {
    local rc
    cmp -s "$1" "$2"; rc=$?
    [ "$rc" -le 1 ] || { note "FAIL  compare audio config $2" >&2; return 2; }
    return "$rc"
  }
  check_directory() {
    local dir="$1" mode
    if [ ! -e "$dir" ] && [ ! -L "$dir" ]; then
      note "WOULD create audio directory $dir"
    elif [ ! -d "$dir" ]; then
      note "FAIL  audio directory is not a directory: $dir"; return 1
    else
      mode="$(stat -Lc %a "$dir")" || return 1
      [ "$mode" = 755 ] || note "WOULD set audio directory permissions: $dir"
    fi
  }
  check_managed_config() {
    local src="$1" dest="$2" marker="$3" candidate rc mode owned=0
    shift 3
    custom_config=1
    [ -r "$src" ] || { note "FAIL  read canonical audio asset $src"; return 1; }
    for candidate in "$@"; do
      [ -r "$candidate" ] || { note "FAIL  read canonical audio asset $candidate"; return 1; }
    done
    if [ ! -e "$dest" ] && [ ! -L "$dest" ]; then
      owned=1
    elif [ ! -L "$dest" ] && [ -f "$dest" ]; then
      for candidate in "$@"; do
        check_compare "$candidate" "$dest"; rc=$?
        [ "$rc" != 2 ] || return 1
        if [ "$rc" = 0 ]; then owned=1; break; fi
      done
    fi
    if [ "$owned" = 0 ]; then
      note "PARTIAL: retained custom audio config $dest"
      return 0
    fi
    custom_config=0
    if [ ! -e "$dest" ]; then
      note "WOULD install audio config $dest"
      printf -v "${marker}_changed" '%s' 1
      return 0
    fi
    check_compare "$src" "$dest"; rc=$?
    [ "$rc" != 2 ] || return 1
    mode="$(stat -c %a "$dest")" || return 1
    if [ "$rc" = 1 ] || [ "$mode" != 644 ]; then
      note "WOULD install audio config $dest"
      printf -v "${marker}_changed" '%s' 1
    fi
  }
  check_remove_config() {
    local dest="$1" marker="$2" candidate="$3" rc
    custom_config=0
    [ -r "$candidate" ] || { note "FAIL  read canonical audio asset $candidate"; return 1; }
    [ -e "$dest" ] || [ -L "$dest" ] || return 0
    if [ -L "$dest" ] || [ ! -f "$dest" ]; then
      custom_config=1
    else
      check_compare "$candidate" "$dest"; rc=$?
      [ "$rc" != 2 ] || return 1
      [ "$rc" = 0 ] || custom_config=1
    fi
    if [ "$custom_config" = 1 ]; then
      note "PARTIAL: retained custom audio config $dest"
    else
      note "WOULD remove audio config $dest"
      printf -v "${marker}_changed" '%s' 1
    fi
  }
  check_audio() {
    local rnnoise lsp=unknown lv2_plugins speaker dir mic_service template pattern prefix suffix existing volume
    local rc mode dropin old_rule mic_config_custom=1 mic_service_custom=0
    local pipewire_changed=0 wireplumber_changed=0 mic_changed=0 uid properties line load="" active="" enabled=""
    local running installed current app
    check_audio_packages || return 1
    local paths=() p
    for p in /usr/lib /usr/lib64; do [ ! -d "$p" ] || paths+=("$p"); done
    [ "${#paths[@]}" -gt 0 ] || { note "FAIL  inspect RNNoise plugin"; return 1; }
    rnnoise="$(find "${paths[@]}" -name librnnoise_ladspa.so -print -quit)" || { note "FAIL  inspect RNNoise plugin"; return 1; }
    if command -v lv2ls >/dev/null 2>&1; then
      lv2_plugins="$(lv2ls)" || { note "FAIL  inspect LSP plugins"; return 1; }
      lsp=0
      [[ "$lv2_plugins" != *lsp-plug.in/plugins/lv2/para_equalizer_x16_lr* ]] || lsp=1
    else
      note "PARTIAL: LSP availability is unknown (lv2ls unavailable)"
    fi
    for dir in "$conf" "$HOME/.config/pipewire/filter-chain.conf.d" "$user_systemd/pipewire.service.d" "$HOME/.ladspa" "$state"; do
      check_directory "$dir" || return 1
    done
    if [ "$lsp" = unknown ] && { [ -e "$conf/50-speaker-dsp.conf" ] || [ -L "$conf/50-speaker-dsp.conf" ]; }; then
      note "PARTIAL: retained existing speaker DSP because LSP availability is unknown"
    else
      if [ "$lsp" = 1 ]; then speaker=speaker-dsp.conf; else speaker=speaker-biquad.conf; fi
      check_managed_config "$assets/files/$speaker" "$conf/50-speaker-dsp.conf" pipewire "$assets/files/speaker-dsp.conf" "$assets/files/speaker-biquad.conf" || return 1
    fi
    if [ -n "$rnnoise" ]; then
      check_managed_config "$assets/files/mic-rnnoise.conf" "$conf/60-mic-dsp.conf" pipewire "$assets/files/mic-rnnoise.conf" || return 1
    else
      check_remove_config "$conf/60-mic-dsp.conf" pipewire "$assets/files/mic-rnnoise.conf" || return 1
    fi
    mic_config_custom="$custom_config"
    dropin="$user_systemd/pipewire.service.d/ladspa-path.conf"
    check_managed_config <(printf '%s\n' '[Service]' 'Environment=LADSPA_PATH=%h/.ladspa:/usr/lib/x86_64-linux-gnu/ladspa:/usr/lib/ladspa:/usr/lib64/ladspa') "$dropin" pipewire <(printf '%s\n' '[Service]' 'Environment=LADSPA_PATH=%h/.ladspa:/usr/lib/x86_64-linux-gnu/ladspa:/usr/lib/ladspa:/usr/lib64/ladspa') || return 1

    mic_service="$user_systemd/mic-dsp-link.service"
    template="$(cat "$assets/templates/mic-dsp-link.service.j2")" || { note "FAIL  read microphone link service template"; return 1; }
    pattern='{{ mic_hardware_volume_pct | default(100) }}'
    [[ "$template" == *"$pattern"* ]] || { note "FAIL  invalid microphone link service template"; return 1; }
    if [ -e "$mic_service" ] || [ -L "$mic_service" ]; then
      if [ -f "$mic_service" ] && [ ! -L "$mic_service" ]; then
        existing="$(cat "$mic_service")" || { note "FAIL  read microphone link service"; return 1; }
        prefix="${template%%"$pattern"*}"; suffix="${template#*"$pattern"}"
        if [[ "$existing" == "$prefix"*"$suffix" ]]; then
          volume="${existing#"$prefix"}"; volume="${volume%"$suffix"}"
          [[ "$volume" =~ ^[0-9]+$ ]] || mic_service_custom=1
        else
          mic_service_custom=1
        fi
      else
        mic_service_custom=1
      fi
      [ "$mic_service_custom" = 0 ] || note "PARTIAL: retained custom microphone link service $mic_service"
    elif [ -z "$rnnoise" ]; then
      mic_service_custom=1
    fi
    if [ "$mic_config_custom" = 1 ]; then
      mic_service_custom=1
      note "PARTIAL: microphone link service unchanged because microphone DSP is not managed"
    fi
    if [ -n "$rnnoise" ] && [ "$mic_service_custom" = 0 ]; then
      template="${template//"$pattern"/$mic_volume}"
      if [ -e "$mic_service" ]; then
        check_compare <(printf '%s\n' "$template") "$mic_service"; rc=$?
        [ "$rc" != 2 ] || return 1
        mode="$(stat -c %a "$mic_service")" || return 1
      else
        rc=1; mode=""
      fi
      if [ "$rc" = 1 ] || [ "$mode" != 644 ]; then
        note "WOULD install microphone link service $mic_service"
        mic_changed=1
      fi
    fi
    old_rule="$HOME/.config/wireplumber/main.lua.d/51-speaker-dsp-default.lua"
    check_remove_config "$old_rule" wireplumber "$assets/files/51-speaker-dsp-default.lua" || return 1
    dir="${old_rule%/*}"
    if [ -d "$dir" ] && [ ! -L "$dir" ]; then
      [ -r "$dir" ] && [ -x "$dir" ] || { note "FAIL  inspect WirePlumber rule directory"; return 1; }
      if (
        shopt -s nullglob dotglob
        entries=("$dir"/*)
        [ "${#entries[@]}" = 0 ] || { [ "${#entries[@]}" = 1 ] && [ "${entries[0]}" = "$old_rule" ] && [ "$custom_config" = 0 ]; }
      ); then
        note "WOULD remove empty obsolete WirePlumber rule directory"
      fi
    fi

    uid="$(id -u)" || return 1
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}"
    export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
    systemctl --user show-environment >/dev/null || { note "FAIL  inspect user audio session"; return 1; }
    if [ "$pipewire_changed" = 1 ] || [ "$mic_changed" = 1 ] || [ -e "$state/pipewire" ] || [ -e "$state/mic" ]; then
      note "WOULD reload user service definitions"
    fi
    if [ "$pipewire_changed" = 1 ] || [ -e "$state/pipewire" ]; then note "WOULD restart PipeWire services"; fi
    if [ "$wireplumber_changed" = 1 ] || [ -e "$state/wireplumber" ]; then note "WOULD restart WirePlumber"; fi
    if [ "$mic_service_custom" = 0 ]; then
      properties="$(systemctl --user show mic-dsp-link.service --property=LoadState --property=ActiveState --property=UnitFileState)" || { note "FAIL  inspect microphone link service"; return 1; }
      while IFS= read -r line; do
        case "$line" in LoadState=*) load="${line#*=}" ;; ActiveState=*) active="${line#*=}" ;; UnitFileState=*) enabled="${line#*=}" ;; esac
      done <<< "$properties"
      case "$load" in loaded|not-found|error|masked) ;; *) note "FAIL  inspect microphone service load state"; return 1 ;; esac
      case "$active" in active|inactive|failed|activating|deactivating|reloading|maintenance) ;; *) note "FAIL  inspect microphone service active state"; return 1 ;; esac
      case "$enabled" in enabled|enabled-runtime|disabled|static|indirect|generated|transient|masked|masked-runtime|linked|linked-runtime|alias|bad|'') ;; *) note "FAIL  inspect microphone service enablement"; return 1 ;; esac
      if [ "$load" = error ] || [ "$enabled" = bad ]; then note "FAIL  inspect microphone service definition"; return 1; fi
      if [ -n "$rnnoise" ]; then
        [ "$enabled" = enabled ] || [ "$enabled" = enabled-runtime ] || note "WOULD enable microphone link service"
        if [ "$active" != active ]; then note "WOULD start microphone link service"
        elif [ "$mic_changed" = 1 ] || [ -e "$state/mic" ]; then note "WOULD restart microphone link service"; fi
      elif [ "$load" != not-found ]; then
        [ "$active" != active ] || note "WOULD stop microphone link service"
        if [ "$enabled" = enabled ] || [ "$enabled" = enabled-runtime ]; then note "WOULD disable microphone link service"; fi
      fi
    fi
    if command -v gsettings >/dev/null 2>&1; then
      current="$(gsettings get org.gnome.desktop.sound allow-volume-above-100-percent)" || { note "FAIL  inspect GNOME over-amplification"; return 1; }
      case "$current" in true) ;; false) note "WOULD enable GNOME over-amplification" ;; *) note "FAIL  invalid GNOME over-amplification state"; return 1 ;; esac
    else
      note "PARTIAL: GNOME over-amplification unavailable"
    fi
    if [ -e "$HOME/.config/autostart/com.github.wwmm.easyeffects.desktop" ] || [ -L "$HOME/.config/autostart/com.github.wwmm.easyeffects.desktop" ]; then
      note "WOULD remove Easy Effects autostart"
    fi
    if command -v flatpak >/dev/null 2>&1; then
      running="$(flatpak ps --columns=application)" || { note "FAIL  inspect running Flatpaks"; return 1; }
      installed="$(flatpak list --system --app --columns=application)" || { note "FAIL  inspect installed Flatpaks"; return 1; }
      while IFS= read -r app; do [ "$app" != com.github.wwmm.easyeffects ] || note "WOULD stop Easy Effects Flatpak"; done <<< "$running"
      while IFS= read -r app; do [ "$app" != com.github.wwmm.easyeffects ] || note "WOULD uninstall Easy Effects Flatpak"; done <<< "$installed"
    fi
  }
  step "check PipeWire audio" check_audio
  finish
fi

install_packages() {
  local os_id="" os_like="" supported=0
  if [ -r /etc/os-release ]; then
    # os-release is the system's shell-compatible distribution metadata.
    os_id="$(. /etc/os-release; printf '%s' "${ID:-}")"
    os_like="$(. /etc/os-release; printf '%s' "${ID_LIKE:-}")"
  fi
  if command -v dnf >/dev/null 2>&1; then
    supported=1
    if ! command -v rpm >/dev/null 2>&1 || ! rpm -q lsp-plugins-lv2 noise-suppression-for-voice >/dev/null 2>&1; then
      as_root dnf install -y lsp-plugins-lv2 noise-suppression-for-voice || return 1
    fi
  fi
  if command -v rpm-ostree >/dev/null 2>&1; then
    supported=1
    if ! command -v rpm >/dev/null 2>&1 || ! rpm -q lsp-plugins-lv2 noise-suppression-for-voice >/dev/null 2>&1; then
      as_root rpm-ostree install --apply-live --idempotent lsp-plugins-lv2 noise-suppression-for-voice || return 1
    fi
  fi
  if [[ " $os_id $os_like " == *" arch "* ]]; then
    supported=1
    if ! pacman -Q lsp-plugins noise-suppression-for-voice >/dev/null 2>&1; then
      as_root pacman -S --needed --noconfirm lsp-plugins noise-suppression-for-voice || return 1
    fi
  fi
  if [ "$supported" = 0 ]; then
    if command -v bootc >/dev/null 2>&1; then
      note "PARTIAL: bootc DSP prerequisites must be provided by the image"
    else
      note "PARTIAL: no supported DSP package manager; install prerequisites for this distribution"
    fi
  fi
}
step "DSP prerequisite packages" install_packages

find_rnnoise() {
  local paths=() p
  for p in /usr/lib /usr/lib64; do [ ! -d "$p" ] || paths+=("$p"); done
  [ "${#paths[@]}" -gt 0 ] || { note "No system library directories found" >&2; return 1; }
  find "${paths[@]}" -name librnnoise_ladspa.so -print -quit
}
rnnoise=""
if ! rnnoise="$(find_rnnoise)"; then
  step "detect RNNoise plugin" false
  # A failed search is not proof the plugin is absent: leave the mic alone.
  rnnoise=unknown
fi
lsp=unknown
if command -v lv2ls >/dev/null 2>&1; then
  if lv2_plugins="$(lv2ls)"; then
    lsp=0
    [[ "$lv2_plugins" != *lsp-plug.in/plugins/lv2/para_equalizer_x16_lr* ]] || lsp=1
  else
    note "PARTIAL: lv2ls failed; LSP availability is unknown"
  fi
else
  note "PARTIAL: lv2ls unavailable; LSP availability is unknown"
fi

step "audio directories" install -d -m 0755 "$conf" "$HOME/.config/pipewire/filter-chain.conf.d" "$user_systemd/pipewire.service.d" "$HOME/.ladspa" "$state"

# Persist restart requests, so a failed user-session restart is retried next run.
install_config() {
  local src="$1" dest="$2" marker="$3" changed=0
  if [ ! -f "$dest" ] || ! cmp -s "$src" "$dest" || [ "$(stat -c %a "$dest")" != 644 ]; then changed=1; fi
  if [ "$changed" = 1 ]; then touch "$state/$marker" || return 1; fi
  install_if_changed "$src" "$dest" 0644
}
remove_config() {
  local dest="$1" marker="$2"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    touch "$state/$marker" && rm -f "$dest" || return 1
  fi
}
# Only replace or remove files whose bytes match an old managed asset.
owned_or_absent() {
  local dest="$1" candidate
  shift
  [ -e "$dest" ] || [ -L "$dest" ] || return 0
  for candidate in "$@"; do [ -r "$candidate" ] || return 2; done
  [ ! -L "$dest" ] || return 1
  for candidate in "$@"; do cmp -s "$dest" "$candidate" && return 0; done
  return 1
}
install_managed() {
  local src="$1" dest="$2" marker="$3" rc
  shift 3
  custom_config=1
  if owned_or_absent "$dest" "$@"; then
    install_config "$src" "$dest" "$marker" || return 1
    custom_config=0
  else
    rc=$?
    [ "$rc" = 1 ] || { note "Missing canonical audio asset for $dest" >&2; return 1; }
    note "PARTIAL: retained custom audio config $dest"
  fi
}
remove_managed() {
  local dest="$1" marker="$2" rc
  shift 2
  custom_config=1
  if owned_or_absent "$dest" "$@"; then
    remove_config "$dest" "$marker" || return 1
    custom_config=0
  else
    rc=$?
    [ "$rc" = 1 ] || { note "Missing canonical audio asset for $dest" >&2; return 1; }
    note "PARTIAL: retained custom audio config $dest"
  fi
}
if [ "$lsp" = unknown ] && { [ -e "$conf/50-speaker-dsp.conf" ] || [ -L "$conf/50-speaker-dsp.conf" ]; }; then
  note "PARTIAL: retained existing speaker DSP because LSP availability is unknown"
else
  if [ "$lsp" = 1 ]; then speaker=speaker-dsp.conf; else speaker=speaker-biquad.conf; fi
  [ "$lsp" != unknown ] || note "PARTIAL: installing built-in speaker EQ because LSP availability is unknown"
  step "speaker DSP" install_managed "$assets/files/$speaker" "$conf/50-speaker-dsp.conf" pipewire "$assets/files/speaker-dsp.conf" "$assets/files/speaker-biquad.conf"
fi
mic_config_custom=1
if [ "$rnnoise" = unknown ]; then
  note "PARTIAL: microphone DSP unchanged because plugin detection failed"
elif [ -n "$rnnoise" ]; then
  step "microphone DSP" install_managed "$assets/files/mic-rnnoise.conf" "$conf/60-mic-dsp.conf" pipewire "$assets/files/mic-rnnoise.conf"
  mic_config_custom="$custom_config"
else
  step "remove unavailable microphone DSP" remove_managed "$conf/60-mic-dsp.conf" pipewire "$assets/files/mic-rnnoise.conf"
  mic_config_custom="$custom_config"
fi

write_dropin() {
  local tmp
  tmp="$(mktemp)" || return 1
  printf '%s\n' '[Service]' 'Environment=LADSPA_PATH=%h/.ladspa:/usr/lib/x86_64-linux-gnu/ladspa:/usr/lib/ladspa:/usr/lib64/ladspa' > "$tmp" || { rm -f "$tmp"; return 1; }
  install_managed "$tmp" "$user_systemd/pipewire.service.d/ladspa-path.conf" pipewire "$tmp"
  local rc=$?
  rm -f "$tmp"
  return "$rc"
}
step "PipeWire LADSPA path" write_dropin

mic_service="$user_systemd/mic-dsp-link.service"
mic_service_custom=0
managed_mic_service() {
  local template pattern prefix suffix existing volume
  [ -f "$mic_service" ] && [ ! -L "$mic_service" ] || return 1
  template="$(cat "$assets/templates/mic-dsp-link.service.j2")" || return 2
  pattern='{{ mic_hardware_volume_pct | default(100) }}'
  [[ "$template" == *"$pattern"* ]] || return 2
  prefix="${template%%"$pattern"*}"
  suffix="${template#*"$pattern"}"
  existing="$(cat "$mic_service")" || return 2
  [[ "$existing" == "$prefix"*"$suffix" ]] || return 1
  volume="${existing#"$prefix"}"
  volume="${volume%"$suffix"}"
  [[ "$volume" =~ ^[0-9]+$ ]]
}
if [ -e "$mic_service" ] || [ -L "$mic_service" ]; then
  if managed_mic_service; then :; else
    rc=$?
    mic_service_custom=1
    if [ "$rc" = 1 ]; then
      note "PARTIAL: retained custom microphone link service $mic_service"
    else
      step "read canonical microphone link service" false
    fi
  fi
elif [ "$rnnoise" = "" ]; then
  # A same-named service elsewhere is not ours to disable.
  mic_service_custom=1
fi
if [ "$mic_config_custom" = 1 ]; then
  mic_service_custom=1
  note "PARTIAL: microphone link service unchanged because microphone DSP is not managed"
fi

write_mic_service() {
  local tmp template pattern rc
  mic_service_custom=1
  template="$(cat "$assets/templates/mic-dsp-link.service.j2")" || return 1
  pattern='{{ mic_hardware_volume_pct | default(100) }}'
  [[ "$template" == *"$pattern"* ]] || return 1
  template="${template//"$pattern"/$mic_volume}"
  tmp="$(mktemp)" || return 1
  printf '%s\n' "$template" > "$tmp" || { rm -f "$tmp"; return 1; }
  install_config "$tmp" "$mic_service" mic
  rc=$?
  rm -f "$tmp"
  [ "$rc" != 0 ] || mic_service_custom=0
  return "$rc"
}
if [ "$rnnoise" != unknown ] && [ -n "$rnnoise" ] && [ "$mic_service_custom" = 0 ]; then
  step "microphone link service" write_mic_service
fi

old_rule="$HOME/.config/wireplumber/main.lua.d/51-speaker-dsp-default.lua"
step "remove obsolete WirePlumber rule" remove_managed "$old_rule" wireplumber "$assets/files/51-speaker-dsp-default.lua"
# Do not delete other, user-owned WirePlumber rules.
if [ -d "${old_rule%/*}" ]; then rmdir "${old_rule%/*}" 2>/dev/null || :; fi

# Systemd user managers also work in non-interactive applies with a live session.
uid="$(id -u)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
sync_user_services() {
  local unit_files loaded_units active=0
  systemctl --user show-environment >/dev/null || return 1
  if [ -e "$state/pipewire" ] || [ -e "$state/mic" ]; then
    systemctl --user daemon-reload || return 1
  fi
  if [ -e "$state/pipewire" ]; then
    systemctl --user reset-failed pipewire.service pipewire.socket pipewire-pulse.service pipewire-pulse.socket || note "warn: could not reset all PipeWire failed states"
    systemctl --user restart pipewire pipewire-pulse.socket || return 1
    rm -f "$state/pipewire" || return 1
  fi
  if [ -e "$state/wireplumber" ]; then
    systemctl --user reset-failed wireplumber.service || note "warn: could not reset WirePlumber failed state"
    systemctl --user restart wireplumber || return 1
    rm -f "$state/wireplumber" || return 1
  fi
  [ "$rnnoise" != unknown ] || return 0
  [ "$mic_service_custom" = 0 ] || return 0
  if [ -n "$rnnoise" ]; then
    systemctl --user is-active --quiet mic-dsp-link.service && active=1
    if ! systemctl --user is-enabled --quiet mic-dsp-link.service; then
      systemctl --user enable mic-dsp-link.service || return 1
    fi
    if [ "$active" = 0 ]; then
      systemctl --user start mic-dsp-link.service || return 1
    elif [ -e "$state/mic" ]; then
      systemctl --user restart mic-dsp-link.service || return 1
    fi
    rm -f "$state/mic" || return 1
  else
    unit_files="$(systemctl --user list-unit-files --no-legend --no-pager mic-dsp-link.service)" || return 1
    loaded_units="$(systemctl --user list-units --all --no-legend --no-pager mic-dsp-link.service)" || return 1
    if [ -n "$unit_files" ] || [ -n "$loaded_units" ]; then
      if systemctl --user is-active --quiet mic-dsp-link.service; then
        systemctl --user stop mic-dsp-link.service || return 1
      fi
      if systemctl --user is-enabled --quiet mic-dsp-link.service; then
        systemctl --user disable mic-dsp-link.service || return 1
      fi
    fi
    rm -f "$state/mic" || return 1
  fi
}
step "user audio services" sync_user_services

set_gnome_volume() {
  local current
  current="$(gsettings get org.gnome.desktop.sound allow-volume-above-100-percent)" || return 1
  [ "$current" = true ] || gsettings set org.gnome.desktop.sound allow-volume-above-100-percent true
}
# GNOME is optional and the original role explicitly tolerated its absence.
soft "GNOME over-amplification" set_gnome_volume
step "remove Easy Effects autostart" rm -f "$HOME/.config/autostart/com.github.wwmm.easyeffects.desktop"
# Preserve user-owned Easy Effects presets and settings.
cleanup_easyeffects() {
  local installed running app found=0
  if ! command -v flatpak >/dev/null 2>&1; then
    note "Flatpak unavailable; no Easy Effects Flatpak to remove"
    return 0
  fi
  running="$(flatpak ps --columns=application)" || return 1
  while IFS= read -r app; do
    if [ "$app" = com.github.wwmm.easyeffects ]; then
      flatpak kill com.github.wwmm.easyeffects || return 1
      break
    fi
  done <<< "$running"
  installed="$(flatpak list --system --app --columns=application)" || return 1
  while IFS= read -r app; do [ "$app" != com.github.wwmm.easyeffects ] || found=1; done <<< "$installed"
  [ "$found" = 0 ] || as_root flatpak uninstall --system -y com.github.wwmm.easyeffects
}
step "remove Easy Effects Flatpak" cleanup_easyeffects
finish
