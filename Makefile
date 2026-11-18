CC ?= cc
CFLAGS ?= -O2 -g
CFLAGS += -std=c11 -Wall -Wextra -Wpedantic $(shell pkg-config --cflags x11 xi xtst xfixes xext xrender)
LDLIBS += $(shell pkg-config --libs x11 xi xtst xfixes xext xrender)

.PHONY: all clean check check-e2e

all: click-toggle-indicator

click-toggle-indicator: src/click-toggle-indicator.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

check: click-toggle-indicator
	./tests/integration-xvfb.sh

check-e2e: click-toggle-indicator
	/usr/bin/python3 -m unittest discover -s tests -p 'test_e2e_*.py' -v

clean:
	rm -f click-toggle-indicator
