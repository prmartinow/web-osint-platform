package capturevalidate

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/redpanda-data/benthos/v4/public/service"
)

const (
	pluginName    = "capture_envelope_validate"
	pluginVersion = "0.1.0"
)

func init() {
	spec := service.NewConfigSpec().
		Summary("Validate Web OSINT capture-event envelopes for shadow Redpanda Connect parity checks.").
		Description("This processor keeps valid messages unchanged and returns an error for malformed capture events. It does not perform materialization or external I/O.")

	constructor := func(conf *service.ParsedConfig, mgr *service.Resources) (service.Processor, error) {
		return &processor{
			logger: mgr.Logger(),
			valid:  mgr.Metrics().NewCounter("capture_envelope_validate_valid_total"),
			failed: mgr.Metrics().NewCounter("capture_envelope_validate_failed_total"),
		}, nil
	}
	if err := service.RegisterProcessor(pluginName, spec, constructor); err != nil {
		panic(err)
	}
}

type processor struct {
	logger *service.Logger
	valid  *service.MetricCounter
	failed *service.MetricCounter
}

type captureEvent struct {
	SchemaVersion  string           `json:"schema_version"`
	CollectorRunID string           `json:"collector_run_id"`
	EventIndex     *int             `json:"event_index"`
	SourceProject  string           `json:"source_project"`
	CaptureMethod  string           `json:"capture_method"`
	CapturedAt     string           `json:"captured_at"`
	Posts          []map[string]any `json:"posts"`
	Accounts       []map[string]any `json:"accounts"`
	Media          []map[string]any `json:"media"`
	SearchResults  []map[string]any `json:"search_results"`
	WebDocuments   []map[string]any `json:"web_documents"`
	UserInputs     []map[string]any `json:"user_inputs"`
}

func (p *processor) Process(ctx context.Context, msg *service.Message) (service.MessageBatch, error) {
	raw, err := msg.AsBytes()
	if err != nil {
		p.failed.Incr(1)
		return nil, fmt.Errorf("%s: read message bytes: %w", pluginName, err)
	}
	var event captureEvent
	if err := json.Unmarshal(raw, &event); err != nil {
		p.failed.Incr(1)
		return nil, fmt.Errorf("%s: invalid JSON: %w", pluginName, err)
	}
	if err := validate(event); err != nil {
		p.failed.Incr(1)
		return nil, fmt.Errorf("%s: %w", pluginName, err)
	}
	p.valid.Incr(1)
	return service.MessageBatch{msg}, nil
}

func (p *processor) Close(ctx context.Context) error {
	return nil
}

func validate(event captureEvent) error {
	missing := make([]string, 0, 6)
	if strings.TrimSpace(event.SchemaVersion) == "" {
		missing = append(missing, "schema_version")
	}
	if strings.TrimSpace(event.CollectorRunID) == "" {
		missing = append(missing, "collector_run_id")
	}
	if event.EventIndex == nil {
		missing = append(missing, "event_index")
	}
	if strings.TrimSpace(event.SourceProject) == "" {
		missing = append(missing, "source_project")
	}
	if strings.TrimSpace(event.CaptureMethod) == "" {
		missing = append(missing, "capture_method")
	}
	if strings.TrimSpace(event.CapturedAt) == "" {
		missing = append(missing, "captured_at")
	}
	if len(missing) > 0 {
		return fmt.Errorf("missing required fields: %s", strings.Join(missing, ", "))
	}
	if event.EventIndex != nil && *event.EventIndex < 0 {
		return fmt.Errorf("event_index must be >= 0")
	}
	if evidenceCount(event) == 0 {
		return fmt.Errorf("capture event contains no evidence arrays")
	}
	return nil
}

func evidenceCount(event captureEvent) int {
	return len(event.Posts) +
		len(event.Accounts) +
		len(event.Media) +
		len(event.SearchResults) +
		len(event.WebDocuments) +
		len(event.UserInputs)
}
