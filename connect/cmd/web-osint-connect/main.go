package main

import (
	"context"

	"github.com/redpanda-data/benthos/v4/public/service"

	_ "github.com/prmartinow/web-osint-platform/connect/plugins/capturevalidate"
	_ "github.com/redpanda-data/connect/v4/public/components/kafka"
	_ "github.com/redpanda-data/connect/v4/public/components/pure"
	_ "github.com/redpanda-data/connect/v4/public/components/prometheus"
	_ "github.com/redpanda-data/connect/v4/public/components/redpanda"
)

func main() {
	service.RunCLI(context.Background())
}
