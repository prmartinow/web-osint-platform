FROM golang:1.23-bookworm AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/web-osint-connect ./cmd/web-osint-connect

FROM gcr.io/distroless/static-debian12:nonroot

COPY --from=build /out/web-osint-connect /web-osint-connect
COPY pipelines /pipelines

ENTRYPOINT ["/web-osint-connect"]
CMD ["-c", "/pipelines/capture-shadow-validate.yaml"]
