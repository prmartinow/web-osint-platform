FROM golang:1.23-bookworm AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/webosint-normalizer .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/webosint-normalizer /webosint-normalizer
USER 1000:1000
ENTRYPOINT ["/webosint-normalizer"]
