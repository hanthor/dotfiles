# secret-broker build helper.
# tailscale.com pulls a large dep tree; if /tmp is a small tmpfs, Go's $WORK
# fills it. Redirect Go's scratch to a roomy disk. Override GOTMPDIR if needed.
GOTMPDIR ?= $(HOME)/.cache/gotmp
export GOTMPDIR
export TMPDIR = $(GOTMPDIR)

.PHONY: build test vet fmt run clean

build: | $(GOTMPDIR)
	go build -o secret-broker .

test: | $(GOTMPDIR)
	go test -count=1 ./...

vet: | $(GOTMPDIR)
	go vet ./...

fmt:
	gofmt -w *.go

# Run against the stub source (no real secrets). Needs TS_AUTHKEY in the env.
run: build
	./secret-broker -source=stub -admins=$(ADMINS)

clean:
	rm -f secret-broker

$(GOTMPDIR):
	mkdir -p $(GOTMPDIR)
