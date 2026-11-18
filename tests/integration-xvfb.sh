#!/usr/bin/env bash
set -euo pipefail

if ! command -v Xvfb >/dev/null 2>&1; then
    echo "SKIP: Xvfb is not installed"
    exit 0
fi

display_number=98
while [[ -e /tmp/.X11-unix/X$display_number ]]; do
    ((display_number++))
done
test_display=:$display_number
Xvfb "$test_display" -screen 0 800x600x24 -nolisten tcp >/dev/null 2>&1 &
xvfb_pid=$!
daemon_pid=
grabber_pid=
reader_pid=
test_dir=$(mktemp -d)
cleanup() {
    [[ -z ${daemon_pid:-} ]] || kill "$daemon_pid" 2>/dev/null || true
    [[ -z ${grabber_pid:-} ]] || kill "$grabber_pid" 2>/dev/null || true
    [[ -z ${reader_pid:-} ]] || kill "$reader_pid" 2>/dev/null || true
    [[ -z ${daemon_pid:-} ]] || wait "$daemon_pid" 2>/dev/null || true
    [[ -z ${grabber_pid:-} ]] || wait "$grabber_pid" 2>/dev/null || true
    kill "$xvfb_pid" 2>/dev/null || true
    rm -rf "$test_dir"
}
trap cleanup EXIT

for _ in {1..40}; do
    DISPLAY=$test_display xdpyinfo >/dev/null 2>&1 && break
    sleep 0.05
done

DISPLAY=$test_display xmodmap -e 'keycode 202 = F24'
DISPLAY=$test_display xmodmap -e 'keycode 197 = F19'
DISPLAY=$test_display ./click-toggle-indicator --toggle-keycode 202 \
    --right-toggle-keycode 197 &
daemon_pid=$!
sleep 0.1
pointer_id=$(DISPLAY=$test_display xinput list --id-only "Virtual core XTEST pointer")

DISPLAY=$test_display xdotool key 202
sleep 0.1
if ! DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q 'button\[1\]=down'; then
    echo "FAIL: first toggle did not hold button 1" >&2
    exit 1
fi

DISPLAY=$test_display xdotool key 202
sleep 0.1
if DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q 'button\[1\]=down'; then
    echo "FAIL: second toggle did not release button 1" >&2
    exit 1
fi

echo "PASS: F24 toggled synthetic button 1 down and up"

DISPLAY=$test_display xdotool key 197
sleep 0.1
if ! DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q 'button\[3\]=down'; then
    echo "FAIL: first right toggle did not hold button 3" >&2
    exit 1
fi

DISPLAY=$test_display xdotool key 197
sleep 0.1
if DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q 'button\[3\]=down'; then
    echo "FAIL: second right toggle did not release button 3" >&2
    exit 1
fi

echo "PASS: F19 toggled synthetic button 3 down and up"

assert_buttons_up() {
    if DISPLAY=$test_display xinput query-state "$pointer_id" | grep -Eq 'button\[(1|3)\]=down'; then
        echo "FAIL: $1" >&2
        exit 1
    fi
}

for start_key in 202 197; do
    if [[ $start_key == 202 ]]; then
        cancel_key=197
        cancel_button=3
    else
        cancel_key=202
        cancel_button=1
    fi
    DISPLAY=$test_display xdotool key "$start_key"
    sleep 0.1
    DISPLAY=$test_display xdotool key "$cancel_key"
    sleep 0.1
    assert_buttons_up "opposite-half click did not only release the held button"

    # A fresh click on the cancelling side can now start its own hold.
    DISPLAY=$test_display xdotool key "$cancel_key"
    sleep 0.1
    if ! DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q "button\[$cancel_button\]=down"; then
        echo "FAIL: cancelling side did not rearm for the next click" >&2
        exit 1
    fi
    DISPLAY=$test_display xdotool key "$start_key"
    sleep 0.1
    assert_buttons_up "opposite-half cancellation did not work after rearming"

    # Crossing the midpoint during a cancelling click must not start a new hold.
    DISPLAY=$test_display xdotool key "$start_key"
    sleep 0.1
    DISPLAY=$test_display xdotool keydown "$cancel_key" keydown "$start_key" \
        keyup "$cancel_key" keyup "$start_key"
    sleep 0.1
    assert_buttons_up "crossing the midpoint during cancellation started a new hold"

    DISPLAY=$test_display xdotool key "$start_key"
    sleep 0.1
    DISPLAY=$test_display xdotool keydown "$cancel_key" keyup "$cancel_key" \
        keydown "$start_key" keyup "$start_key"
    sleep 0.1
    assert_buttons_up "a brief key-release gap during cancellation started a new hold"
done
echo "PASS: either half cancels either hold, including midpoint crossings, and rearms"

DISPLAY=$test_display xdotool keydown 202
DISPLAY=$test_display xdotool keydown 197
DISPLAY=$test_display xdotool keyup 202
DISPLAY=$test_display xdotool keyup 197
sleep 0.1
if ! DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q 'button\[1\]=down' ||
    DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q 'button\[3\]=down'; then
    echo "FAIL: crossing the midpoint toggled both buttons" >&2
    exit 1
fi
DISPLAY=$test_display xdotool key 202
sleep 0.1
if DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q 'button\[1\]=down'; then
    echo "FAIL: left toggle did not rearm after the crossed click" >&2
    exit 1
fi
echo "PASS: one crossed click toggled only its starting side"

DISPLAY=$test_display xdotool keydown 197 keyup 197 keydown 202 keyup 202
sleep 0.1
if ! DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q 'button\[3\]=down' ||
    DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q 'button\[1\]=down'; then
    echo "FAIL: reverse key transition toggled both buttons" >&2
    exit 1
fi
DISPLAY=$test_display xdotool key 197
sleep 0.1
if DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q 'button\[3\]=down'; then
    echo "FAIL: right toggle did not rearm after the crossed click" >&2
    exit 1
fi
echo "PASS: reverse key transition toggled only its starting side"

${CC:-cc} -std=c11 -Wall -Wextra -Wpedantic -o "$test_dir/grab-keyboard" \
    "$(dirname "$0")/grab-keyboard.c" $(pkg-config --cflags --libs x11)
DISPLAY=$test_display "$test_dir/grab-keyboard" >"$test_dir/grab-ready" &
grabber_pid=$!
for _ in {1..40}; do
    [[ -s "$test_dir/grab-ready" ]] && break
    sleep 0.05
done
if [[ ! -s "$test_dir/grab-ready" ]]; then
    echo "FAIL: could not grab the keyboard for regression test" >&2
    exit 1
fi

DISPLAY=$test_display xdotool key 202
sleep 0.1
if ! DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q 'button\[1\]=down'; then
    echo "FAIL: key toggle was lost during another client's keyboard grab" >&2
    exit 1
fi
DISPLAY=$test_display xdotool key 202
sleep 0.1
if DISPLAY=$test_display xinput query-state "$pointer_id" | grep -q 'button\[1\]=down'; then
    echo "FAIL: key toggle did not release during another client's keyboard grab" >&2
    exit 1
fi
echo "PASS: F24 toggled during another client's keyboard grab"

kill "$grabber_pid"
wait "$grabber_pid" 2>/dev/null || true
grabber_pid=
kill "$daemon_pid"
wait "$daemon_pid"
daemon_pid=

# The Shell bridge consumes states rather than moving X11 overlay windows.
DISPLAY=$test_display ./click-toggle-indicator --toggle-keycode 202 \
    --right-toggle-keycode 197 --state-stdout >"$test_dir/states" &
daemon_pid=$!
sleep 0.1
for key_and_state in '202 1' '197 0' '197 2' '202 0'; do
    read -r key expected <<<"$key_and_state"
    DISPLAY=$test_display xdotool key "$key"
    sleep 0.1
    if [[ $(tail -n 1 "$test_dir/states") != "$expected" ]]; then
        echo "FAIL: state output did not match the held side" >&2
        exit 1
    fi
done
DISPLAY=$test_display xdotool key 197
sleep 0.1
kill "$daemon_pid"
wait "$daemon_pid"
daemon_pid=
assert_buttons_up "state-output daemon left a button held on exit"
if [[ $(tail -n 1 "$test_dir/states") != 0 ]]; then
    echo "FAIL: state output was not cleared on exit" >&2
    exit 1
fi
echo "PASS: external indicator state tracks both holds, cancellation, and shutdown"

# Losing the bridge must release a button even without another click.
mkfifo "$test_dir/state-pipe"
head -n 2 <"$test_dir/state-pipe" >"$test_dir/pipe-states" &
reader_pid=$!
DISPLAY=$test_display ./click-toggle-indicator --toggle-keycode 202 \
    --right-toggle-keycode 197 --state-stdout >"$test_dir/state-pipe" &
daemon_pid=$!
sleep 0.1
DISPLAY=$test_display xdotool key 202
for _ in {1..40}; do
    kill -0 "$daemon_pid" 2>/dev/null || break
    sleep 0.05
done
if kill -0 "$daemon_pid" 2>/dev/null; then
    echo "FAIL: daemon did not exit when its state reader disappeared" >&2
    exit 1
fi
wait "$reader_pid"
reader_pid=
wait "$daemon_pid"
daemon_pid=
assert_buttons_up "lost state reader stranded a synthetic button"
echo "PASS: losing the display bridge releases the synthetic button"
