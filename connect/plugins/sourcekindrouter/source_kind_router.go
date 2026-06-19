package sourcekindrouter

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/prmartinow/web-osint-platform/connect/internal/webosint"
	"github.com/redpanda-data/benthos/v4/public/service"
)

const (
	pluginName    = "source_kind_router"
	pluginVersion = "0.1.0"
)

func init() {
	spec := service.NewConfigSpec().
		Summary("Annotate Web OSINT capture events with deterministic source-kind routing metadata.").
		Description("This processor keeps the capture message unchanged and writes source-kind counts to message metadata for shadow Connect parity checks.")

	constructor := func(conf *service.ParsedConfig, mgr *service.Resources) (service.Processor, error) {
		return &processor{
			routed: mgr.Metrics().NewCounter("source_kind_router_routed_total"),
			failed: mgr.Metrics().NewCounter("source_kind_router_failed_total"),
		}, nil
	}
	if err := service.RegisterProcessor(pluginName, spec, constructor); err != nil {
		panic(err)
	}
}

type processor struct {
	routed *service.MetricCounter
	failed *service.MetricCounter
}

func (p *processor) Process(ctx context.Context, msg *service.Message) (service.MessageBatch, error) {
	raw, err := msg.AsBytes()
	if err != nil {
		incr(p.failed, 1)
		return nil, fmt.Errorf("%s: read message bytes: %w", pluginName, err)
	}
	event, err := webosint.ParseCaptureEvent(raw)
	if err != nil {
		incr(p.failed, 1)
		return nil, fmt.Errorf("%s: parse capture event: %w", pluginName, err)
	}
	counts := webosint.SourceKindCounts(event)
	kinds := webosint.SourceKinds(event)
	countsJSON, err := json.Marshal(counts)
	if err != nil {
		incr(p.failed, 1)
		return nil, fmt.Errorf("%s: marshal route counts: %w", pluginName, err)
	}
	msg.MetaSet("source_kind_router_plugin", pluginName)
	msg.MetaSet("source_kind_router_version", pluginVersion)
	msg.MetaSet("source_kind_router_primary", primaryKind(kinds))
	msg.MetaSet("source_kind_router_kinds", strings.Join(kinds, ","))
	msg.MetaSet("source_kind_router_counts", string(countsJSON))
	msg.MetaSet("source_kind_router_total", strconv.Itoa(total(counts)))
	incr(p.routed, 1)
	return service.MessageBatch{msg}, nil
}

func (p *processor) Close(ctx context.Context) error {
	return nil
}

func primaryKind(kinds []string) string {
	if len(kinds) == 0 {
		return ""
	}
	return kinds[0]
}

func total(counts map[string]int) int {
	keys := make([]string, 0, len(counts))
	for key := range counts {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	n := 0
	for _, key := range keys {
		n += counts[key]
	}
	return n
}

func incr(counter *service.MetricCounter, n int64) {
	if counter != nil {
		counter.Incr(n)
	}
}
