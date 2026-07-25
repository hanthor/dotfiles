# Multi-stage build for the secret-broker (in-cluster / Talos option, #49).
# Produces a small static image. NOTE: for -source=bw the image must ALSO carry
# the `bw` CLI (npm i -g @bitwarden/cli) — so a distroless-static base won't work
# for the bw path; use a node-based runtime, or a k8s-secret source. With
# -source=stub (placeholders) the static image below is sufficient.

FROM golang:1.26-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
# Static build so it runs on distroless. tsnet is pure-Go, so CGO can stay off.
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /secret-broker .

# distroless static ships CA certs (tsnet needs outbound TLS to the coordination
# server) and runs as a non-root user.
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /secret-broker /usr/local/bin/secret-broker
USER nonroot:nonroot
ENTRYPOINT ["/usr/local/bin/secret-broker"]
