#include <X11/Xlib.h>
#include <stdio.h>
#include <unistd.h>

int main(void) {
    Display *display = XOpenDisplay(NULL);
    if (display == NULL) return 1;
    Window root = DefaultRootWindow(display);
    if (XGrabKeyboard(display, root, False, GrabModeAsync, GrabModeAsync,
                      CurrentTime) != GrabSuccess) {
        XCloseDisplay(display);
        return 1;
    }
    XSync(display, False);
    puts("ready");
    fflush(stdout);
    sleep(3);
    XUngrabKeyboard(display, CurrentTime);
    XCloseDisplay(display);
    return 0;
}
