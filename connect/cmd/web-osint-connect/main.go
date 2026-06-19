package main

import (
	"context"

	"github.com/redpanda-data/benthos/v4/public/service"

	_ "github.com/prmartinow/web-osint-platform/connect/plugins/capturevalidate"
	_ "github.com/prmartinow/web-osint-platform/connect/plugins/dlqenricher"
	_ "github.com/prmartinow/web-osint-platform/connect/plugins/mediarequestbuilder"
	_ "github.com/prmartinow/web-osint-platform/connect/plugins/observedeventprojector"
	_ "github.com/prmartinow/web-osint-platform/connect/plugins/sourcekindrouter"
	_ "github.com/redpanda-data/connect/v4/public/components/kafka"
	_ "github.com/redpanda-data/connect/v4/public/components/prometheus"
	_ "github.com/redpanda-data/connect/v4/public/components/pure"
	_ "github.com/redpanda-data/connect/v4/public/components/redpanda"
)

func main() {
	service.RunCLI(context.Background())
}
