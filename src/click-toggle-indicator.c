#define _POSIX_C_SOURCE 200809L

#include <X11/Xlib.h>
#include <X11/keysym.h>
#include <X11/extensions/XTest.h>
#include <X11/extensions/XInput2.h>
#include <X11/extensions/shape.h>
#include <X11/extensions/Xfixes.h>
#include <X11/extensions/Xrender.h>
#include <errno.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static volatile sig_atomic_t running = 1;
static int x_error_code = 0;

static void stop_running(int signal_number) {
    (void)signal_number;
    running = 0;
}

static int remember_x_error(Display *display, XErrorEvent *error) {
    (void)display;
    x_error_code = error->error_code;
    return 0;
}

static void usage(FILE *stream, const char *program) {
    fprintf(stream,
            "Usage: %s [options]\n"
            "\n"
            "Toggle a synthetic X11 mouse-button hold and show an indicator.\n"
            "\n"
            "Options:\n"
            "  --toggle-keycode N X11 keycode (default: 202)\n"
            "  --toggle-key NAME  keysym alternative to --toggle-keycode\n"
            "  --toggle-button N  mouse-button alternative to --toggle-key\n"
            "  --hold-button N    button held synthetically (default: 1)\n"
            "  --right-toggle-keycode N  second X11 keycode for a shared click cycle\n"
            "  --right-hold-button N    button held by the second key (default: 3)\n"
            "  --right-offset-x N     second indicator horizontal offset (default: 30)\n"
            "  --size N           indicator diameter, 8..96 (default: 18)\n"
            "  --offset-x N       horizontal cursor offset (default: 18)\n"
            "  --offset-y N       vertical cursor offset (default: 18)\n"
            "  --color COLOR      X11 color name or #rrggbb (default: #3b82f6)\n"
            "  --opacity N        indicator opacity, 0.05..1.0 (default: 0.65)\n"
            "  --help             show this help\n",
            program);
}

static bool parse_int(const char *text, int minimum, int maximum, int *result) {
    char *end = NULL;
    errno = 0;
    long value = strtol(text, &end, 10);
    if (errno != 0 || text == end || *end != '\0' || value < minimum || value > maximum) {
        return false;
    }
    *result = (int)value;
    return true;
}

static bool parse_double(const char *text, double minimum, double maximum, double *result) {
    char *end = NULL;
    errno = 0;
    double value = strtod(text, &end);
    if (errno != 0 || text == end || *end != '\0' || value < minimum || value > maximum) {
        return false;
    }
    *result = value;
    return true;
}

static Window create_indicator(Display *display, Window root, int screen, int size,
                               const char *color_name, double opacity) {
    XColor color;
    Colormap colormap = DefaultColormap(display, screen);
    if (!XParseColor(display, colormap, color_name, &color)) {
        fprintf(stderr, "Invalid or unavailable X11 color: %s\n", color_name);
        return None;
    }

    XVisualInfo visual_info;
    bool has_argb = XMatchVisualInfo(display, screen, 32, TrueColor, &visual_info);
    XRenderPictFormat *window_format =
        has_argb ? XRenderFindVisualFormat(display, visual_info.visual) : NULL;
    has_argb = window_format != NULL && window_format->type == PictTypeDirect &&
               window_format->direct.alphaMask != 0;

    Visual *visual = has_argb ? visual_info.visual : DefaultVisual(display, screen);
    int depth = has_argb ? visual_info.depth : DefaultDepth(display, screen);
    if (has_argb) {
        colormap = XCreateColormap(display, root, visual, AllocNone);
    } else if (!XAllocColor(display, colormap, &color)) {
        fprintf(stderr, "Could not allocate X11 color: %s\n", color_name);
        return None;
    }

    XSetWindowAttributes attributes = {0};
    attributes.override_redirect = True;
    attributes.background_pixel = has_argb ? 0 : color.pixel;
    attributes.border_pixel = 0;
    attributes.colormap = colormap;
    attributes.save_under = True;
    Window window = XCreateWindow(display, root, 0, 0, (unsigned int)size,
                                  (unsigned int)size, 0, depth, InputOutput, visual,
                                  CWOverrideRedirect | CWBackPixel | CWBorderPixel |
                                      CWColormap | CWSaveUnder,
                                  &attributes);
    if (window == None) {
        return None;
    }

    Pixmap mask = XCreatePixmap(display, root, (unsigned int)size, (unsigned int)size, 1);
    GC mask_gc = XCreateGC(display, mask, 0, NULL);
    XSetForeground(display, mask_gc, 0);
    XFillRectangle(display, mask, mask_gc, 0, 0, (unsigned int)size, (unsigned int)size);
    XSetForeground(display, mask_gc, 1);
    XFillArc(display, mask, mask_gc, 0, 0, (unsigned int)size, (unsigned int)size, 0,
             360 * 64);
    XShapeCombineMask(display, window, ShapeBounding, 0, 0, mask, ShapeSet);
    XFreeGC(display, mask_gc);
    XFreePixmap(display, mask);

    XserverRegion empty_region = XFixesCreateRegion(display, NULL, 0);
    XFixesSetWindowShapeRegion(display, window, ShapeInput, 0, 0, empty_region);
    XFixesDestroyRegion(display, empty_region);

    (void)opacity;
    return window;
}

static void draw_indicator(Display *display, Window window, int screen, int size,
                           const char *color_name, double opacity) {
    XWindowAttributes attributes;
    if (!XGetWindowAttributes(display, window, &attributes)) return;
    XRenderPictFormat *format = XRenderFindVisualFormat(display, attributes.visual);
    if (format == NULL || format->type != PictTypeDirect || format->direct.alphaMask == 0) {
        return;
    }

    XColor color;
    if (!XParseColor(display, DefaultColormap(display, screen), color_name, &color)) return;
    Picture destination = XRenderCreatePicture(display, window, format, 0, NULL);
    XRenderColor render_color = {
        .red = color.red,
        .green = color.green,
        .blue = color.blue,
        .alpha = (unsigned short)(opacity * 65535.0 + 0.5),
    };
    Picture source = XRenderCreateSolidFill(display, &render_color);
    XRenderComposite(display, PictOpSrc, source, None, destination, 0, 0, 0, 0,
                     0, 0, (unsigned int)size, (unsigned int)size);
    XRenderFreePicture(display, source);
    XRenderFreePicture(display, destination);
}

static void move_indicator(Display *display, Window root, Window indicator, int screen,
                           int size, int offset_x, int offset_y) {
    Window root_return, child_return;
    int root_x, root_y, window_x, window_y;
    unsigned int mask;
    if (!XQueryPointer(display, root, &root_return, &child_return, &root_x, &root_y,
                       &window_x, &window_y, &mask)) {
        return;
    }
    int x = root_x + offset_x;
    int y = root_y + offset_y;
    int max_x = DisplayWidth(display, screen) - size;
    int max_y = DisplayHeight(display, screen) - size;
    if (x > max_x) x = root_x - offset_x - size;
    if (y > max_y) y = root_y - offset_y - size;
    if (x < 0) x = 0;
    if (y < 0) y = 0;
    XMoveWindow(display, indicator, x, y);
}

int main(int argc, char **argv) {
    int toggle_button = 0;
    int toggle_keycode_value = 202;
    const char *toggle_key_name = NULL;
    int hold_button = 1;
    int right_toggle_keycode = 0;
    int right_hold_button = 3;
    int right_offset_x = 30;
    int size = 18;
    int offset_x = 18;
    int offset_y = 18;
    const char *color = "#3b82f6";
    double opacity = 0.65;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--help") == 0) {
            usage(stdout, argv[0]);
            return EXIT_SUCCESS;
        }
        if (i + 1 >= argc) {
            fprintf(stderr, "Missing value for %s\n", argv[i]);
            usage(stderr, argv[0]);
            return EXIT_FAILURE;
        }
        const char *option = argv[i++];
        const char *value = argv[i];
        if (strcmp(option, "--toggle-button") == 0) {
            if (!parse_int(value, 1, 255, &toggle_button)) goto invalid_value;
            toggle_key_name = NULL;
            toggle_keycode_value = 0;
        } else if (strcmp(option, "--toggle-keycode") == 0) {
            if (!parse_int(value, 8, 255, &toggle_keycode_value)) goto invalid_value;
            toggle_key_name = NULL;
            toggle_button = 0;
        } else if (strcmp(option, "--toggle-key") == 0) {
            toggle_key_name = value;
            toggle_keycode_value = 0;
            toggle_button = 0;
        } else if (strcmp(option, "--hold-button") == 0) {
            if (!parse_int(value, 1, 255, &hold_button)) goto invalid_value;
        } else if (strcmp(option, "--right-toggle-keycode") == 0) {
            if (!parse_int(value, 8, 255, &right_toggle_keycode)) goto invalid_value;
        } else if (strcmp(option, "--right-hold-button") == 0) {
            if (!parse_int(value, 1, 255, &right_hold_button)) goto invalid_value;
        } else if (strcmp(option, "--right-offset-x") == 0) {
            if (!parse_int(value, -512, 512, &right_offset_x)) goto invalid_value;
        } else if (strcmp(option, "--size") == 0) {
            if (!parse_int(value, 8, 96, &size)) goto invalid_value;
        } else if (strcmp(option, "--offset-x") == 0) {
            if (!parse_int(value, -512, 512, &offset_x)) goto invalid_value;
        } else if (strcmp(option, "--offset-y") == 0) {
            if (!parse_int(value, -512, 512, &offset_y)) goto invalid_value;
        } else if (strcmp(option, "--color") == 0) {
            color = value;
        } else if (strcmp(option, "--opacity") == 0) {
            if (!parse_double(value, 0.05, 1.0, &opacity)) goto invalid_value;
        } else {
            fprintf(stderr, "Unknown option: %s\n", option);
            usage(stderr, argv[0]);
            return EXIT_FAILURE;
        }
        continue;
invalid_value:
        fprintf(stderr, "Invalid value for %s: %s\n", option, value);
        return EXIT_FAILURE;
    }

    if (toggle_button != 0 && toggle_button == hold_button) {
        fprintf(stderr, "The toggle and held buttons must be different.\n");
        return EXIT_FAILURE;
    }
    if (right_toggle_keycode != 0 &&
        (toggle_keycode_value == 0 || right_toggle_keycode == toggle_keycode_value ||
         right_hold_button == hold_button)) {
        fprintf(stderr, "The two toggle keys and held buttons must be distinct.\n");
        return EXIT_FAILURE;
    }

    Display *display = XOpenDisplay(NULL);
    if (display == NULL) {
        fprintf(stderr, "Cannot open X display. Is DISPLAY set and is this an X11 session?\n");
        return EXIT_FAILURE;
    }
    int event_base, error_base, major, minor;
    if (!XTestQueryExtension(display, &event_base, &error_base, &major, &minor)) {
        fprintf(stderr, "The XTEST extension is unavailable on this X server.\n");
        XCloseDisplay(display);
        return EXIT_FAILURE;
    }

    int screen = DefaultScreen(display);
    Window root = RootWindow(display, screen);
    KeyCode toggle_keycode = (KeyCode)toggle_keycode_value;
    if (toggle_key_name != NULL) {
        KeySym keysym = XStringToKeysym(toggle_key_name);
        if (keysym == NoSymbol || (toggle_keycode = XKeysymToKeycode(display, keysym)) == 0) {
            fprintf(stderr, "Unknown or unmapped X11 keysym: %s\n", toggle_key_name);
            XCloseDisplay(display);
            return EXIT_FAILURE;
        }
    }
    int xi_opcode = 0;
    if (toggle_keycode != 0) {
        int xi_event_base, xi_error_base;
        int xi_major = 2, xi_minor = 1;
        if (!XQueryExtension(display, "XInputExtension", &xi_opcode, &xi_event_base,
                             &xi_error_base) ||
            XIQueryVersion(display, &xi_major, &xi_minor) != Success ||
            xi_major < 2 || (xi_major == 2 && xi_minor < 1)) {
            fprintf(stderr, "XInput 2.1 is required for key toggles during window grabs.\n");
            XCloseDisplay(display);
            return EXIT_FAILURE;
        }
    }
    Window indicators[2] = {
        create_indicator(display, root, screen, size, color, opacity), None
    };
    if (indicators[0] == None) {
        fprintf(stderr, "Could not create the hold indicator window.\n");
        XCloseDisplay(display);
        return EXIT_FAILURE;
    }
    if (right_toggle_keycode != 0) {
        indicators[1] = create_indicator(display, root, screen, size, color, opacity);
        if (indicators[1] == None) {
            fprintf(stderr, "Could not create the second hold indicator window.\n");
            XDestroyWindow(display, indicators[0]);
            XCloseDisplay(display);
            return EXIT_FAILURE;
        }
    }

    XSetErrorHandler(remember_x_error);
    if (toggle_keycode != 0) {
        unsigned char mask_bytes[XIMaskLen(XI_RawKeyRelease)] = {0};
        XIEventMask mask = {.deviceid = XIAllMasterDevices,
                            .mask_len = sizeof(mask_bytes), .mask = mask_bytes};
        XISetMask(mask_bytes, XI_RawKeyPress);
        XISetMask(mask_bytes, XI_RawKeyRelease);
        XISelectEvents(display, root, &mask, 1);
        XGrabKey(display, (int)toggle_keycode, AnyModifier, root, False,
                 GrabModeAsync, GrabModeAsync);
        if (right_toggle_keycode != 0) {
            XGrabKey(display, right_toggle_keycode, AnyModifier, root, False,
                     GrabModeAsync, GrabModeAsync);
        }
    } else {
        XGrabButton(display, (unsigned int)toggle_button, AnyModifier, root, False,
                    ButtonPressMask | ButtonReleaseMask, GrabModeAsync, GrabModeAsync,
                    None, None);
    }
    XSync(display, False);
    if (x_error_code != 0) {
        fprintf(stderr,
                "Could not grab toggle input (X11 error %d). Another program may own it.\n",
                x_error_code);
        XDestroyWindow(display, indicators[0]);
        if (indicators[1] != None) XDestroyWindow(display, indicators[1]);
        XCloseDisplay(display);
        return EXIT_FAILURE;
    }

    struct sigaction action = {0};
    action.sa_handler = stop_running;
    sigemptyset(&action.sa_mask);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGHUP, &action, NULL);

    bool held[2] = {false, false};
    bool key_is_down[2] = {false, false};
    int keycodes[2] = {(int)toggle_keycode, right_toggle_keycode};
    int buttons[2] = {hold_button, right_hold_button};
    int offsets_x[2] = {offset_x, right_offset_x};
    int active_key = -1;
    struct timespec last_release = {0};
    /* Input Remapper can release one mapped key just before pressing the other. */
    const long switch_grace_ns = 50000000L;
    const struct timespec frame_delay = {.tv_sec = 0, .tv_nsec = 16000000L};

    while (running) {
        while (XPending(display) > 0) {
            XEvent event;
            XNextEvent(display, &event);
            int key_index = -1;
            bool toggle_press = false;
            bool toggle_release = false;
            if (toggle_keycode != 0 && event.type == GenericEvent &&
                event.xcookie.extension == xi_opcode && XGetEventData(display, &event.xcookie)) {
                if (event.xcookie.evtype == XI_RawKeyPress ||
                    event.xcookie.evtype == XI_RawKeyRelease) {
                    XIRawEvent *raw = event.xcookie.data;
                    for (int index = 0; index < (right_toggle_keycode ? 2 : 1); index++) {
                        if (raw->detail == keycodes[index]) key_index = index;
                    }
                    if (key_index >= 0) {
                        toggle_press = event.xcookie.evtype == XI_RawKeyPress;
                        toggle_release = event.xcookie.evtype == XI_RawKeyRelease;
                    }
                }
                XFreeEventData(display, &event.xcookie);
            } else if (toggle_button != 0) {
                toggle_press = event.type == ButtonPress &&
                               event.xbutton.button == (unsigned int)toggle_button;
                toggle_release = event.type == ButtonRelease &&
                                 event.xbutton.button == (unsigned int)toggle_button;
                if (toggle_press || toggle_release) key_index = 0;
            }
            if (toggle_press && key_index >= 0 && !key_is_down[key_index]) {
                key_is_down[key_index] = true;
                bool same_click = right_toggle_keycode != 0 &&
                                  key_is_down[1 - key_index];
                if (!same_click && right_toggle_keycode != 0 &&
                    key_index != active_key && last_release.tv_sec != 0) {
                    struct timespec now;
                    clock_gettime(CLOCK_MONOTONIC, &now);
                    long long elapsed = (long long)(now.tv_sec - last_release.tv_sec) *
                                        1000000000LL + now.tv_nsec - last_release.tv_nsec;
                    same_click = elapsed < switch_grace_ns;
                }
                if (same_click) continue;
                active_key = key_index;
                held[key_index] = !held[key_index];
                XTestFakeButtonEvent(display, (unsigned int)buttons[key_index],
                                     held[key_index] ? True : False,
                                     CurrentTime);
                if (held[key_index]) {
                    move_indicator(display, root, indicators[key_index], screen, size,
                                   offsets_x[key_index], offset_y);
                    XMapRaised(display, indicators[key_index]);
                    draw_indicator(display, indicators[key_index], screen, size, color,
                                   opacity);
                } else {
                    XUnmapWindow(display, indicators[key_index]);
                }
                XFlush(display);
            } else if (toggle_release && key_index >= 0) {
                key_is_down[key_index] = false;
                if (active_key == key_index) {
                    clock_gettime(CLOCK_MONOTONIC, &last_release);
                }
            }
        }
        if (toggle_keycode != 0) {
            char keys[32];
            XQueryKeymap(display, keys);
            for (int index = 0; index < (right_toggle_keycode ? 2 : 1); index++) {
                if ((keys[keycodes[index] / 8] & (1 << (keycodes[index] % 8))) == 0) {
                    /* A grabbed key may have no matching raw release event. */
                    if (key_is_down[index] && active_key == index) {
                        clock_gettime(CLOCK_MONOTONIC, &last_release);
                    }
                    key_is_down[index] = false;
                }
            }
        }
        for (int index = 0; index < (right_toggle_keycode ? 2 : 1); index++) {
            if (held[index]) {
                move_indicator(display, root, indicators[index], screen, size,
                               offsets_x[index], offset_y);
                XFlush(display);
            }
        }
        if (!key_is_down[0] && !key_is_down[1] && last_release.tv_sec != 0) {
            struct timespec now;
            clock_gettime(CLOCK_MONOTONIC, &now);
            long long elapsed = (long long)(now.tv_sec - last_release.tv_sec) *
                                1000000000LL + now.tv_nsec - last_release.tv_nsec;
            if (elapsed >= switch_grace_ns) {
                active_key = -1;
                last_release.tv_sec = 0;
            }
        }
        nanosleep(&frame_delay, NULL);
    }

    for (int index = 0; index < (right_toggle_keycode ? 2 : 1); index++) {
        if (held[index]) {
            XTestFakeButtonEvent(display, (unsigned int)buttons[index], False, CurrentTime);
        }
    }
    if (toggle_keycode != 0) {
        XUngrabKey(display, (int)toggle_keycode, AnyModifier, root);
        if (right_toggle_keycode != 0) {
            XUngrabKey(display, right_toggle_keycode, AnyModifier, root);
        }
    } else {
        XUngrabButton(display, (unsigned int)toggle_button, AnyModifier, root);
    }
    XDestroyWindow(display, indicators[0]);
    if (indicators[1] != None) XDestroyWindow(display, indicators[1]);
    XSync(display, False);
    XCloseDisplay(display);
    return EXIT_SUCCESS;
}
