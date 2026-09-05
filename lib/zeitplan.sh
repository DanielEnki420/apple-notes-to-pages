#!/bin/bash
# zeitplan.sh — automatischen Export ein- und ausschalten (launchd)
#
# macOS startet wiederkehrende Aufgaben ueber launchd, nicht ueber cron.
# Diese Datei wird von export-notes eingebunden.

# Wird normalerweise von export-notes eingebunden, das tzeile mitbringt.
# Fuer den Einzelgebrauch hier eine Rueckfallebene.
if ! declare -f tzeile >/dev/null 2>&1; then
  tzeile() { if [ "${SPRACHE:-de}" = "de" ]; then echo "$1"; else echo "$2"; fi; }
fi

ETIKETT="de.danielenki.apple-notes-export"
PLIST="$HOME/Library/LaunchAgents/$ETIKETT.plist"

zeitplan_status() {
  if [ ! -f "$PLIST" ]; then
    tzeile "  Kein Zeitplan eingerichtet." "  No schedule set up."
    return 0
  fi
  # PlistBuddy meldet fehlende Schluessel als Text auf der Standardausgabe,
  # nicht ueber den Fehlerkanal. Deshalb muss geprueft werden, ob wirklich
  # eine Zahl zurueckkam.
  plist_zahl() {
    local wert
    wert="$(/usr/libexec/PlistBuddy -c "Print :StartCalendarInterval:$1" \
            "$PLIST" 2>/dev/null)"
    case "$wert" in
      ''|*[!0-9]*) echo "" ;;
      *) echo "$wert" ;;
    esac
  }
  local stunde minute takt
  stunde="$(plist_zahl Hour)"
  minute="$(plist_zahl Minute)"
  takt="$(plist_zahl Weekday)"
  if [ -n "$takt" ]; then
    tzeile "  Eingerichtet: woechentlich, sonntags um $(printf '%02d:%02d' "${stunde:-0}" "${minute:-0}")" "  Set up: weekly, Sundays at $(printf '%02d:%02d' "${stunde:-0}" "${minute:-0}")"
  else
    tzeile "  Eingerichtet: taeglich um $(printf '%02d:%02d' "${stunde:-0}" "${minute:-0}")" "  Set up: daily at $(printf '%02d:%02d' "${stunde:-0}" "${minute:-0}")"
  fi
  if launchctl list 2>/dev/null | grep -q "$ETIKETT"; then
    tzeile "  Status: aktiv" "  Status: active"
  else
    tzeile "  Status: eingetragen, aber nicht geladen" "  Status: registered but not loaded"
  fi
  tzeile "  Datei:  ${PLIST/#$HOME/~}" "  File:   ${PLIST/#$HOME/~}"
}

zeitplan_aus() {
  if [ ! -f "$PLIST" ]; then
    tzeile "  Es war kein Zeitplan eingerichtet." "  No schedule was set up."
    return 0
  fi
  launchctl bootout "gui/$(id -u)/$ETIKETT" 2>/dev/null \
    || launchctl unload "$PLIST" 2>/dev/null
  rm -f "$PLIST"
  tzeile "  Zeitplan entfernt." "  Schedule removed."
}

# In einer plist sind &, < und > Sonderzeichen. Pfade duerfen sie enthalten
# (z. B. ein Ordner mit "&" im Namen), deshalb muss maskiert werden — sonst
# entsteht ungueltiges XML, das launchd zwar noch laedt, jedes andere
# Werkzeug aber ablehnt.
xml_maskieren() {
  printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

# zeitplan_ein <taeglich|woechentlich> <HH:MM> <projektpfad> <weitere argumente>
zeitplan_ein() {
  local takt="$1" uhrzeit="$2" pfad="$3"; shift 3
  local stunde="${uhrzeit%%:*}" minute="${uhrzeit##*:}"
  stunde="$((10#$stunde))"; minute="$((10#$minute))"

  mkdir -p "$HOME/Library/LaunchAgents" "$pfad/logs"
  local wochentag=""
  [ "$takt" = "woechentlich" ] && wochentag="
      <key>Weekday</key><integer>0</integer>"

  local pfad_x log_x
  pfad_x="$(xml_maskieren "$pfad")"
  log_x="$(xml_maskieren "$pfad/logs/zeitplan.log")"

  cat > "$PLIST" <<PLISTENDE
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$ETIKETT</string>
  <key>ProgramArguments</key>
  <array>
    <string>$pfad_x/export-notes</string>
$(for a in "$@"; do echo "    <string>$(xml_maskieren "$a")</string>"; done)
  </array>
  <key>WorkingDirectory</key><string>$pfad_x</string>
  <key>StartCalendarInterval</key>
  <dict>
      <key>Hour</key><integer>$stunde</integer>
      <key>Minute</key><integer>$minute</integer>$wochentag
  </dict>
  <key>StandardOutPath</key><string>$log_x</string>
  <key>StandardErrorPath</key><string>$log_x</string>
  <key>RunAtLoad</key><false/>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PLISTENDE

  if ! plutil -lint "$PLIST" >/dev/null 2>&1; then
    tzeile "  ✗ Die Zeitplan-Datei waere fehlerhaft geworden — nichts eingerichtet." "  ✗ The schedule file would have been malformed — nothing was set up."
    plutil -lint "$PLIST" 2>&1 | sed 's/^/    /'
    rm -f "$PLIST"
    return 1
  fi

  launchctl bootout "gui/$(id -u)/$ETIKETT" 2>/dev/null
  if launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null \
     || launchctl load "$PLIST" 2>/dev/null; then
    tzeile "  ✓ Zeitplan eingerichtet: $takt um $uhrzeit" "  ✓ Schedule set up: $takt at $uhrzeit"
    tzeile "    Argumente: ${*:-(keine)}" "    Arguments: ${*:-(none)}"
    echo ""
    if [ "${SPRACHE:-de}" = "de" ]; then
      echo "    Zu beachten: Beim automatischen Lauf oeffnet sich Pages kurz"
      echo "    sichtbar — das laesst sich nicht vermeiden, Pages exportiert"
      echo "    nur im Vordergrund. Waehle deshalb eine Uhrzeit, zu der du"
      echo "    nicht am Rechner arbeitest."
      echo ""
      echo "    Beim ersten Lauf fragt macOS einmalig nach der Erlaubnis,"
      echo "    Notizen und Pages zu steuern. Diese Rueckfrage muss bestaetigt"
      echo "    werden, sonst bricht der automatische Export ab."
    else
      echo "    Note: during an automated run Pages briefly opens on screen."
      echo "    That is unavoidable — Pages only exports in the foreground."
      echo "    Pick a time when you are not working at the machine."
      echo ""
      echo "    On the first run macOS asks once for permission to control"
      echo "    Notes and Pages. That prompt has to be confirmed, otherwise"
      echo "    the scheduled export aborts."
    fi
  else
    tzeile "  ✗ Der Zeitplan konnte nicht geladen werden." "  ✗ The schedule could not be loaded."
    rm -f "$PLIST"
    return 1
  fi
}
